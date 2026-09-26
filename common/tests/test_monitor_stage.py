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


def test_main_writes_a_summary_with_all_four_sections(monitor, tmp_path, monkeypatch):
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
        assert set(summary["parts"]) == {"feature", "prediction", "performance", "input_quality"}
        assert summary["parts"]["performance"] in ("ok", "warning", "high")
        assert set(summary["current_metrics"]) == {"rmse", "mae", "r2"}
        assert summary["input_quality"]["level"] in ("ok", "warning", "high")
        assert summary["flush"]["ok"] is True
        assert summary["group_metrics"]["current"]["city"]["boston"]["n"] >= 1
        assert set(summary["consecutive_warnings"]) == set(summary["parts"])
        assert store.exists(storage_module.report_key("m", "run1", "html"))
