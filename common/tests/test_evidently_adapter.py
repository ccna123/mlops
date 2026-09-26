"""The adapter, against results saved from a real Evidently 0.7.23 run.

The fixtures in fixtures/evidently_0_7/ were produced by Evidently itself. If an
Evidently upgrade changes its result layout, re-generate them with the new
version: these tests are then the first thing to fail, and the adapter the only
code to fix.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from ml_common import evidently_adapter as adapter
from ml_common.metrics import compute_metrics

FIXTURES = Path(__file__).parent / "fixtures" / "evidently_0_7"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _value_drift(column: str, threshold: float, value: float) -> dict:
    return {
        "config": {"type": adapter.VALUE_DRIFT_TYPE, "column": column, "threshold": threshold},
        "value": value,
    }


# --- data drift ----------------------------------------------------------------


def test_real_drift_result_gives_a_share_and_one_margin_per_column():
    summary = _load("data_drift.json")
    assert 0.0 <= adapter.drifted_share(summary) <= 1.0
    assert len(adapter.feature_margins(summary)) == 2


def test_feature_margins_returns_one_value_per_usable_entry():
    summary = {"metrics": [_value_drift("city", 0.1, 0.775448),
                           _value_drift("bedrooms", 0.1, 0.051171)]}
    assert adapter.feature_margins(summary) == pytest.approx([0.675448, -0.048829])


def test_feature_margins_raises_when_every_entry_is_missing_threshold():
    # Returning [] here would make the severity "ok" on a report nobody could read.
    summary = {"metrics": [{"config": {"type": adapter.VALUE_DRIFT_TYPE}, "value": 0.9}]}
    with pytest.raises(KeyError):
        adapter.feature_margins(summary)


def test_feature_margins_raises_when_there_are_no_value_drift_entries():
    with pytest.raises(KeyError):
        adapter.feature_margins({"metrics": []})


def test_feature_margins_skips_one_malformed_entry_and_keeps_the_good_one():
    summary = {"metrics": [_value_drift("city", 0.1, 0.775448),
                           {"config": {"type": adapter.VALUE_DRIFT_TYPE}, "value": 0.8}]}
    assert adapter.feature_margins(summary) == pytest.approx([0.675448])


def test_drifted_share_raises_rather_than_reporting_zero():
    with pytest.raises(KeyError):
        adapter.drifted_share({"metrics": []})


# --- data quality of the input -------------------------------------------------


def test_real_quality_result_reads_missing_and_unseen_shares():
    numbers = adapter.quality_numbers(_load("quality.json"))
    assert numbers["bedrooms"] == {"missing_share": 0.5, "unseen_share": None}
    assert numbers["city"]["missing_share"] == 0.25
    # "denver" twice among 3 present values; the missing one is not "unseen".
    assert numbers["city"]["unseen_share"] == pytest.approx(2 / 3)


# --- performance: Evidently's numbers equal evaluation's (CN-32) ---------------


def test_regression_metrics_match_what_evaluation_computes():
    data = pd.read_csv(FIXTURES / "performance_regression_data.csv")
    from_evidently = adapter.performance_metrics(_load("performance_regression.json"),
                                                 "regression")
    from_evaluation = compute_metrics("regression", data["actual"], data["prediction"])
    assert from_evidently == pytest.approx(from_evaluation)


def test_classification_metrics_match_evaluation_at_the_model_threshold():
    data = pd.read_csv(FIXTURES / "performance_classification_data.csv")
    threshold = 0.4  # the probas_threshold the fixture was produced with
    from_evidently = adapter.performance_metrics(
        _load("performance_classification.json"), "classification"
    )
    from_evaluation = compute_metrics(
        "classification",
        data["actual"],
        data["probability"] >= threshold,
        data["probability"],
    )
    assert from_evidently == pytest.approx(from_evaluation)


def test_performance_leaves_out_what_the_report_does_not_hold():
    assert adapter.performance_metrics({"metrics": []}, "regression") == {}
