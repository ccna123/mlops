"""The monitor stage's own Evidently calls, run against real Evidently.

`stages/monitor/main.py` is loaded by path (stages are not a package). Skipped
where the file or Evidently is absent: the ml-base image holds only common/
and no Evidently, so inside it these tests skip rather than fail collection.
The adapter itself is tested without Evidently in test_evidently_adapter.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml_common import evidently_adapter as adapter
from ml_common.metrics import compute_metrics

_PATH = Path(__file__).resolve().parents[2] / "stages" / "monitor" / "main.py"

pytestmark = pytest.mark.skipif(
    not _PATH.exists() or importlib.util.find_spec("evidently") is None,
    reason="needs stages/monitor/main.py and Evidently (dev machine or CI, not ml-base)",
)


@pytest.fixture(scope="module")
def monitor():
    spec = importlib.util.spec_from_file_location("monitor_main_under_test", _PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_regression_performance_equals_what_evaluation_computes(monitor):
    rng = np.random.default_rng(1)
    actual = rng.normal(400_000, 80_000, 200)
    joined = pd.DataFrame({"actual": actual, "prediction": actual + rng.normal(0, 30_000, 200)})
    summary = monitor.performance_report(joined, "regression", 0.5).dict()
    assert adapter.performance_metrics(summary, "regression") == pytest.approx(
        compute_metrics("regression", joined["actual"], joined["prediction"])
    )


def test_classification_performance_equals_evaluation_at_the_threshold(monitor):
    rng = np.random.default_rng(2)
    actual = rng.random(200) < 0.25
    probability = np.clip(actual * 0.3 + rng.random(200) * 0.7, 0, 1)
    threshold = 0.35
    joined = pd.DataFrame({"actual": actual, "probability": probability,
                           "prediction": probability >= threshold})
    summary = monitor.performance_report(joined, "classification", threshold).dict()
    assert adapter.performance_metrics(summary, "classification") == pytest.approx(
        compute_metrics("classification", actual, probability >= threshold, probability)
    )


def test_quality_report_counts_missing_and_unseen_after_cleaning(monitor):
    raw = pd.DataFrame({"city": ["BOSTON", "denver", None, "Miami"],
                        "bedrooms": [3, None, 2, None]})
    cleaned = monitor.clean_for_drift(raw)
    known = monitor.known_categories(
        pd.DataFrame({"city": ["  boston ", "MIAMI", "boston"]}), ["city"]
    )
    assert known == {"city": ["boston", "miami"]}
    numbers = adapter.quality_numbers(
        monitor.quality_report(cleaned, ["bedrooms"], ["city"], known).dict()
    )
    assert numbers["bedrooms"]["missing_share"] == 0.5
    assert numbers["city"]["missing_share"] == 0.25
    assert numbers["city"]["unseen_share"] == pytest.approx(1 / 3)


def _regression_joined(seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    actual = rng.normal(400_000, 80_000, 200)
    return pd.DataFrame({"actual": actual, "prediction": actual + rng.normal(0, 30_000, 200)})


def test_performance_detail_report_renders_regression_plots(monitor):
    snapshot = monitor.performance_detail_report(_regression_joined(), "regression", 0.5)
    assert len(snapshot._widgets) > 3


def test_performance_detail_report_renders_classification_at_the_threshold(monitor):
    rng = np.random.default_rng(2)
    actual = rng.random(200) < 0.25
    probability = np.clip(actual * 0.3 + rng.random(200) * 0.7, 0, 1)
    joined = pd.DataFrame({"actual": actual, "probability": probability,
                           "prediction": probability >= 0.35})
    snapshot = monitor.performance_detail_report(joined, "classification", 0.35)
    assert len(snapshot._widgets) > 3


def _trace_names(snapshot) -> set[str]:
    import json
    import re

    names: set[str] = set()
    for widget in snapshot._widgets:
        names.update(re.findall(r'"name": "([^"]{1,40})"', json.dumps(widget.dict(), default=str)))
    return names


def test_performance_detail_report_overlays_the_test_set_error_distribution(monitor):
    served = _regression_joined(1).assign(prediction=lambda f: f["prediction"] - 80_000)
    snapshot = monitor.performance_detail_report(
        served, "regression", 0.5, reference=_regression_joined(2)
    )
    assert {"current", "reference"} <= _trace_names(snapshot)


def test_performance_detail_report_takes_a_classification_reference(monitor):
    def joined(seed):
        rng = np.random.default_rng(seed)
        actual = rng.random(200) < 0.25
        probability = np.clip(actual * 0.3 + rng.random(200) * 0.7, 0, 1)
        return pd.DataFrame({"actual": actual, "probability": probability,
                             "prediction": probability >= 0.35})

    alone = monitor.performance_detail_report(joined(1), "classification", 0.35)
    beside = monitor.performance_detail_report(
        joined(1), "classification", 0.35, reference=joined(2)
    )
    assert len(beside._widgets) > len(alone._widgets)


class _FixedModel:
    """Predicts from the living area alone, so the expected frame is known exactly."""

    def predict(self, frame):
        return frame["living_area_sqft"].to_numpy() * 100.0

    def predict_proba(self, frame):
        p = (frame["living_area_sqft"].to_numpy() > 2000).astype(float) * 0.8 + 0.1
        return np.column_stack([1 - p, p])


def test_test_set_performance_frame_scores_the_champion_on_a_capped_sample(monitor):
    test_df = pd.DataFrame({"living_area_sqft": [1000.0, 1500.0, 2500.0, 3000.0],
                            "sale_price": [110_000.0, 140_000.0, 260_000.0, 310_000.0]})
    frame = monitor.test_set_performance_frame(_FixedModel(), test_df, "regression", 0.5, 3)
    assert list(frame.columns) == ["actual", "prediction"]
    assert len(frame) == 3
    assert (frame["prediction"] == frame["actual"].map(
        dict(zip(test_df["sale_price"], test_df["living_area_sqft"] * 100.0, strict=True))
    )).all()


def test_test_set_performance_frame_for_classification_applies_the_threshold(monitor):
    test_df = pd.DataFrame({"living_area_sqft": [1000.0, 2500.0],
                            "needs_renovation": [False, True]})
    frame = monitor.test_set_performance_frame(_FixedModel(), test_df, "classification", 0.5, 10)
    assert list(frame.columns) == ["actual", "probability", "prediction"]
    assert frame["probability"].tolist() == pytest.approx([0.1, 0.9])
    assert frame["prediction"].tolist() == [False, True]
    assert frame["actual"].tolist() == [False, True]


def test_data_summary_report_compares_only_the_named_columns(monitor):
    rng = np.random.default_rng(3)
    current = pd.DataFrame({"a": rng.normal(0, 1, 100), "c": rng.choice(["x", "y"], 100),
                            "property_id": [f"p{i}" for i in range(100)]})
    reference = current.assign(a=rng.normal(0.5, 1, 100))
    snapshot = monitor.data_summary_report(reference, current, ["a"], ["c"])
    html = monitor.combined_html([("Data summary", snapshot)]).decode("utf-8")
    assert "property_id" not in html


def test_combined_html_is_one_page_with_a_titled_section_per_report(monitor):
    performance = monitor.performance_detail_report(_regression_joined(), "regression", 0.5)
    quality = monitor.quality_report(
        pd.DataFrame({"bedrooms": [3.0, None], "city": ["boston", None]}),
        ["bedrooms"], ["city"], {"city": ["boston"]},
    )
    html = monitor.combined_html(
        [("Performance on served traffic", performance), ("Input quality", quality)]
    ).decode("utf-8")
    assert html.count("<html") == 1
    assert "Performance on served traffic" in html
    assert "Input quality" in html


def _raw_houses(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    living = rng.uniform(800, 4000, n)
    return pd.DataFrame({
        "property_id": [f"p{seed}-{i}" for i in range(n)],
        "listing_date": ["2023-07-15"] * n,
        "city": rng.choice(["Boston", "MIAMI", "tulsa"], n),
        "state": ["MA"] * n,
        "zipcode": ["02134"] * n,
        "property_type": rng.choice(["condo", "Single_Family"], n),
        "living_area_sqft": living,
        "bedrooms": rng.integers(1, 6, n).astype(float),
        "condition": ["good"] * n,
        "sale_price": living * 150 + rng.normal(0, 20_000, n),
    })


def _run_main(monitor, tmp_path, monkeypatch, *, with_test_split: bool = True) -> tuple[dict, str]:
    """Runs main() against moto and a file MLflow store; returns (summary, report html)."""
    import json as _json
    from datetime import UTC, datetime

    import boto3
    import mlflow
    import mlflow.sklearn
    from mlflow import MlflowClient
    from moto import mock_aws

    from ml_common import storage as storage_module
    from ml_common.estimators import build_model
    from ml_common.features import build_pipeline

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="monitor-test")
        store = storage_module.Storage(None, "k", "s", "monitor-test")
        monkeypatch.setattr(monitor.Storage, "from_env", classmethod(lambda cls: store))

        tracking = f"file:{tmp_path / 'mlruns'}"
        mlflow.set_tracking_uri(tracking)
        train = _raw_houses(400, 1)
        pipeline = build_pipeline("regression", build_model("regression", "ridge"))
        pipeline.fit(train.drop(columns=["sale_price"]), train["sale_price"])
        mlflow.set_experiment("m")
        with mlflow.start_run() as run:
            mlflow.log_param("fingerprint", "dataid")
            mlflow.log_metrics({"test_rmse": 25_000.0, "test_mae": 20_000.0, "test_r2": 0.8})
            mlflow.sklearn.log_model(pipeline, artifact_path="model")
        version = mlflow.register_model(f"runs:/{run.info.run_id}/model", "m").version
        MlflowClient().set_registered_model_alias("m", "champion", version)
        store.write_parquet(train, storage_module.processed_key("dataid", "regression", "train"))
        if with_test_split:
            store.write_parquet(
                _raw_houses(150, 3), storage_module.processed_key("dataid", "regression", "test")
            )

        served = _raw_houses(120, 2)
        now = datetime.now(UTC)
        log = pd.DataFrame({
            "request_id": [f"r{i}" for i in range(120)],
            "timestamp": [now.isoformat()] * 120,
            "raw_input": [_json.dumps(r) for r in
                          served.drop(columns=["sale_price"]).to_dict("records")],
            "prediction": pipeline.predict(served.drop(columns=["sale_price"])),
            "probability": [None] * 120,
            "model_name": ["m"] * 120,
            "model_version": [str(version)] * 120,
        })
        store.write_parquet(log, storage_module.inference_log_key("m", now.date(), "a1"))
        truth = pd.DataFrame({"request_id": log["request_id"],
                              "predicted_on": now.date().isoformat(),
                              "actual": served["sale_price"], "model_name": "m"})
        store.write_parquet(truth, storage_module.ground_truth_key("m", now.date(), "b1"))

        for key, value in {"TASK_TYPE": "regression", "MODEL_NAME": "m",
                           "MLFLOW_TRACKING_URI": tracking, "MONITOR_RUN_ID": "run1",
                           "FLUSH_RESULT": '{"ok": true, "written": 3, "error": null}'}.items():
            monkeypatch.setenv(key, value)
        assert monitor.main() == 0

        summary = store.read_json(storage_module.drift_latest_key("m"))
        html = store.read_bytes(storage_module.report_key("m", "run1", "html")).decode("utf-8")
    return summary, html


def test_main_writes_a_summary_with_all_four_sections(monitor, tmp_path, monkeypatch):
    summary, _ = _run_main(monitor, tmp_path, monkeypatch)
    assert set(summary["parts"]) == {"feature", "prediction", "performance", "input_quality"}
    assert summary["parts"]["performance"] in ("ok", "warning", "high")
    assert set(summary["current_metrics"]) == {"rmse", "mae", "r2"}
    assert summary["input_quality"]["level"] in ("ok", "warning", "high")
    assert summary["flush"]["ok"] is True
    assert summary["group_metrics"]["current"]["city"]["boston"]["n"] >= 1
    assert set(summary["consecutive_warnings"]) == set(summary["parts"])


def test_main_report_page_holds_every_section(monitor, tmp_path, monkeypatch):
    _, html = _run_main(monitor, tmp_path, monkeypatch)
    for title in monitor.REPORT_SECTION_TITLES.values():
        assert title in html


def test_main_report_page_sets_served_performance_against_the_test_set(
    monitor, tmp_path, monkeypatch
):
    _, html = _run_main(monitor, tmp_path, monkeypatch)
    assert "Reference: Model Quality" in html


def test_main_without_a_test_split_still_grades_and_shows_served_performance_alone(
    monitor, tmp_path, monkeypatch
):
    summary, html = _run_main(monitor, tmp_path, monkeypatch, with_test_split=False)
    assert summary["parts"]["performance"] in ("ok", "warning", "high")
    assert monitor.REPORT_SECTION_TITLES["performance"] in html
    assert "Current: Model Quality" in html
    assert "Reference: Model Quality" not in html


def test_main_report_page_leaves_input_quality_to_the_dashboard(monitor, tmp_path, monkeypatch):
    summary, html = _run_main(monitor, tmp_path, monkeypatch)
    assert summary["input_quality"]["level"] in ("ok", "warning", "high")
    assert "Input quality" not in html
    assert "values out of list" not in html


def test_a_failing_display_only_report_leaves_the_verdict_and_the_rest_of_the_page(
    monitor, tmp_path, monkeypatch
):
    def broken(*args, **kwargs):
        raise ValueError("evidently could not render this")

    monkeypatch.setattr(monitor, "performance_detail_report", broken)
    summary, html = _run_main(monitor, tmp_path, monkeypatch)
    assert summary["parts"]["performance"] in ("ok", "warning", "high")
    assert monitor.REPORT_SECTION_TITLES["performance"] not in html
    assert monitor.REPORT_SECTION_TITLES["feature"] in html
