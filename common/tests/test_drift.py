"""Tests for the pure-pandas half of monitoring.

Nothing here imports Evidently: that is the whole reason the severity rules
and the window handling live in common/ instead of in the monitor stage.
"""

import json
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from ml_common import drift


def test_days_in_window_covers_a_single_day():
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    assert drift.days_in_window(end, 6) == [date(2026, 9, 20)]


def test_days_in_window_spans_midnight():
    # 24 hours back from 09:00 reaches into the previous day.
    end = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
    assert drift.days_in_window(end, 24) == [date(2026, 9, 19), date(2026, 9, 20)]


def test_days_in_window_spans_three_days():
    end = datetime(2026, 9, 20, 1, 0, tzinfo=UTC)
    assert drift.days_in_window(end, 48) == [
        date(2026, 9, 18),
        date(2026, 9, 19),
        date(2026, 9, 20),
    ]


def test_decode_raw_inputs_turns_json_strings_back_into_columns():
    frame = pd.DataFrame(
        {
            "request_id": ["r1", "r2"],
            "raw_input": [
                json.dumps({"city": "boston", "bedrooms": 3}),
                json.dumps({"city": "miami", "bedrooms": 4}),
            ],
        }
    )
    result = drift.decode_raw_inputs(frame)
    assert list(result.columns) == ["city", "bedrooms"]
    assert result["city"].tolist() == ["boston", "miami"]
    assert result["bedrooms"].tolist() == [3, 4]


def test_decode_raw_inputs_fills_missing_keys_with_none():
    # Serving accepts a record that omits an optional column, so two rows in
    # the same log can carry different keys.
    frame = pd.DataFrame(
        {
            "request_id": ["r1", "r2"],
            "raw_input": [
                json.dumps({"city": "boston", "bedrooms": 3}),
                json.dumps({"city": "miami"}),
            ],
        }
    )
    result = drift.decode_raw_inputs(frame)
    assert result["bedrooms"].tolist()[0] == 3
    assert pd.isna(result["bedrooms"].tolist()[1])


def test_decode_raw_inputs_on_empty_frame_returns_empty():
    frame = pd.DataFrame({"request_id": [], "raw_input": []})
    assert len(drift.decode_raw_inputs(frame)) == 0


def test_join_outcomes_keeps_only_rows_with_ground_truth():
    predictions = pd.DataFrame(
        {"request_id": ["r1", "r2", "r3"], "prediction": [100.0, 200.0, 300.0]}
    )
    outcomes = pd.DataFrame({"request_id": ["r1", "r3"], "actual": [110.0, 280.0]})

    joined = drift.join_outcomes(predictions, outcomes)

    assert joined["request_id"].tolist() == ["r1", "r3"]
    assert joined["prediction"].tolist() == [100.0, 300.0]
    assert joined["actual"].tolist() == [110.0, 280.0]


def test_join_outcomes_ignores_feedback_for_unknown_requests():
    # Feedback can arrive for a prediction served before the window started.
    predictions = pd.DataFrame({"request_id": ["r1"], "prediction": [100.0]})
    outcomes = pd.DataFrame({"request_id": ["r1", "older"], "actual": [110.0, 999.0]})

    joined = drift.join_outcomes(predictions, outcomes)

    assert len(joined) == 1
    assert joined["request_id"].tolist() == ["r1"]


def test_join_outcomes_with_no_feedback_returns_empty_not_error():
    predictions = pd.DataFrame({"request_id": ["r1"], "prediction": [100.0]})
    outcomes = pd.DataFrame({"request_id": [], "actual": []})

    joined = drift.join_outcomes(predictions, outcomes)

    assert len(joined) == 0
    assert "prediction" in joined.columns


class FakeStorage:
    """Stands in for Storage: keys to DataFrames, no boto3 and no MinIO."""

    def __init__(self, frames: dict):
        self._frames = frames

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self._frames if k.startswith(prefix))

    def read_parquet(self, key: str) -> pd.DataFrame:
        return self._frames[key]


def test_load_predictions_concatenates_every_part_in_the_window():
    frames = {
        "inference-log/m/dt=2026-09-20/part-a.parquet": pd.DataFrame(
            {"request_id": ["r1"], "prediction": [1.0], "timestamp": ["2026-09-20T17:00:00Z"]}
        ),
        "inference-log/m/dt=2026-09-20/part-b.parquet": pd.DataFrame(
            {"request_id": ["r2"], "prediction": [2.0], "timestamp": ["2026-09-20T17:30:00Z"]}
        ),
    }
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)

    result = drift.load_predictions(FakeStorage(frames), "m", end, 6)

    assert sorted(result["request_id"].tolist()) == ["r1", "r2"]


def test_load_predictions_reads_both_days_when_the_window_spans_midnight():
    frames = {
        "inference-log/m/dt=2026-09-19/part-a.parquet": pd.DataFrame(
            {
                "request_id": ["yesterday"],
                "prediction": [1.0],
                "timestamp": ["2026-09-19T23:00:00Z"],
            }
        ),
        "inference-log/m/dt=2026-09-20/part-b.parquet": pd.DataFrame(
            {"request_id": ["today"], "prediction": [2.0], "timestamp": ["2026-09-20T08:00:00Z"]}
        ),
    }
    end = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)

    result = drift.load_predictions(FakeStorage(frames), "m", end, 24)

    assert sorted(result["request_id"].tolist()) == ["today", "yesterday"]


def test_load_predictions_with_no_traffic_returns_empty_frame():
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    result = drift.load_predictions(FakeStorage({}), "m", end, 6)
    assert len(result) == 0


def test_load_predictions_excludes_rows_outside_the_hour_cutoff_same_day_partition():
    # Two agent batches land in the SAME day partition an hour apart. A
    # short window must isolate the second batch, or MONITOR_WINDOW_HOURS=1
    # would be a lie: two scenarios run back to back on the same day would
    # silently mix, which is exactly the contamination the monitor stage
    # exists to avoid between runs.
    frames = {
        "inference-log/m/dt=2026-09-20/part-a.parquet": pd.DataFrame(
            {
                "request_id": ["earlier_batch"],
                "prediction": [1.0],
                "timestamp": ["2026-09-20T06:30:00Z"],
            }
        ),
        "inference-log/m/dt=2026-09-20/part-b.parquet": pd.DataFrame(
            {
                "request_id": ["later_batch"],
                "prediction": [2.0],
                "timestamp": ["2026-09-20T07:55:00Z"],
            }
        ),
    }
    end = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)

    result = drift.load_predictions(FakeStorage(frames), "m", end, 1)

    assert result["request_id"].tolist() == ["later_batch"]


def test_load_outcomes_reads_the_ground_truth_prefix():
    frames = {
        "ground-truth/m/dt=2026-09-20/part-a.parquet": pd.DataFrame(
            {"request_id": ["r1"], "actual": [110.0]}
        ),
    }
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)

    result = drift.load_outcomes(FakeStorage(frames), "m", end, 6)

    assert result["actual"].tolist() == [110.0]


def test_load_predictions_skips_a_day_that_has_no_files():
    frames = {
        "inference-log/m/dt=2026-09-20/part-a.parquet": pd.DataFrame(
            {"request_id": ["r1"], "prediction": [1.0], "timestamp": ["2026-09-20T08:30:00Z"]}
        ),
    }
    end = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)

    # 2026-09-19 has no traffic at all; that is silence, not an error.
    result = drift.load_predictions(FakeStorage(frames), "m", end, 24)

    assert result["request_id"].tolist() == ["r1"]


@pytest.mark.parametrize(
    ("share", "expected"),
    [
        (0.0, "ok"),
        (0.29, "ok"),
        (0.3, "warning"),
        (0.5, "warning"),
        (0.51, "high"),
        (1.0, "high"),
    ],
)
def test_feature_severity_thresholds(share, expected):
    assert drift.feature_severity(share) == expected


def test_feature_severity_without_margins_is_unchanged():
    # The share-only call signature from before task-11's market_shift
    # addendum must keep working exactly as it did - no caller is forced to
    # supply margins.
    assert drift.feature_severity(0.0909) == "ok"
    assert drift.feature_severity(0.5) == "warning"


@pytest.mark.parametrize(
    ("total_margin", "expected"),
    [
        (-0.2844, "ok"),  # observed: scenario=none, task-11 addendum
        (-0.01, "ok"),
        (0.0, "warning"),
        (0.3901, "warning"),  # observed: market_shift, task-11 addendum
    ],
)
def test_feature_margin_severity_thresholds(total_margin, expected):
    # A single margin whose sum is the total_margin under test - the
    # function only cares about the sum, not the individual values.
    assert drift.feature_margin_severity([total_margin]) == expected


def test_feature_margin_severity_with_no_columns_is_ok():
    # No ValueDrift metrics were extractable (e.g. an empty feature set) -
    # "ok" is the safe default, the same way an empty share is "ok".
    assert drift.feature_margin_severity([]) == "ok"


def test_feature_severity_share_dilutes_but_magnitude_catches_market_shift():
    # Exercises the rule this pair of paths exists to implement, not a
    # replay of any one report: when the SAME drifted-columns share comes
    # from two different situations - a run with no real drift vs. a run
    # where drift is concentrated into a couple of columns - share alone
    # cannot tell them apart (it only counts how many columns crossed
    # their threshold, not by how much), but the summed margin can, because
    # a column that behaves identically in both runs contributes an
    # identical amount to both sums and cancels out of the comparison,
    # leaving only the genuine difference visible.
    #
    # The share value and the two margin sums below are representative,
    # not arbitrary: they are the real numbers task-11's market_shift
    # addendum measured (fingerprint 1630bf27520bba7f - see
    # FEATURE_MAGNITUDE_WARNING's comment and the task-11 report for the
    # full per-column breakdown), used here as realistic motivation for
    # the constant, not as fixture data this test depends on reproducing.
    share = 2 / 22  # 0.0909..., identical in both real runs
    no_drift_margins_sum = -0.2844
    concentrated_drift_margins_sum = 0.3901

    assert drift.feature_severity(share, [no_drift_margins_sum]) == "ok"
    assert drift.feature_severity(share, [concentrated_drift_margins_sum]) == "warning"


def test_prediction_severity_is_binary():
    assert drift.prediction_severity(False) == "ok"
    assert drift.prediction_severity(True) == "high"


def test_performance_severity_says_insufficient_below_the_floor():
    # Not "ok". A green badge when nobody has checked is the dangerous lie.
    result = drift.performance_severity(
        "regression", {"rmse": 41_000.0}, {"rmse": 41_000.0}, n_joined=10
    )
    assert result == "insufficient_data"


def test_performance_severity_at_exactly_the_floor_is_measured():
    result = drift.performance_severity(
        "regression", {"rmse": 41_000.0}, {"rmse": 41_000.0}, n_joined=drift.MIN_GROUND_TRUTH
    )
    assert result == "ok"


@pytest.mark.parametrize(
    ("current_rmse", "expected"),
    [
        (41_000.0, "ok"),
        (49_199.0, "ok"),
        (49_200.0, "warning"),
        (61_500.0, "warning"),
        (61_501.0, "high"),
    ],
)
def test_performance_severity_regression_uses_the_rmse_ratio(current_rmse, expected):
    # Train rmse 41_000: warning at 1.2x = 49_200, high above 1.5x = 61_500.
    result = drift.performance_severity(
        "regression", {"rmse": current_rmse}, {"rmse": 41_000.0}, n_joined=500
    )
    assert result == expected


@pytest.mark.parametrize(
    ("current_auc", "expected"),
    [
        (0.72, "ok"),
        (0.71, "ok"),
        (0.65, "warning"),
        (0.61, "warning"),
        (0.60, "high"),
    ],
)
def test_performance_severity_classification_uses_the_auc_drop(current_auc, expected):
    # Train auc 0.71: warning once it drops 0.05, high once it drops 0.10.
    result = drift.performance_severity(
        "classification", {"auc": current_auc}, {"auc": 0.71}, n_joined=500
    )
    assert result == expected


def test_performance_severity_improving_is_never_worse_than_ok():
    result = drift.performance_severity(
        "regression", {"rmse": 20_000.0}, {"rmse": 41_000.0}, n_joined=500
    )
    assert result == "ok"


def test_overall_severity_takes_the_worst():
    result = drift.overall_severity({"feature": "ok", "prediction": "ok", "performance": "ok"})
    assert result == "ok"
    assert (
        drift.overall_severity({"feature": "warning", "prediction": "ok", "performance": "ok"})
        == "warning"
    )
    assert (
        drift.overall_severity({"feature": "warning", "prediction": "high", "performance": "ok"})
        == "high"
    )


def test_overall_severity_ignores_insufficient_data():
    # Unmeasured must not drag the verdict up OR down.
    result = drift.overall_severity(
        {"feature": "ok", "prediction": "ok", "performance": "insufficient_data"}
    )
    assert result == "ok"

    result = drift.overall_severity(
        {"feature": "high", "prediction": "ok", "performance": "insufficient_data"}
    )
    assert result == "high"


def test_overall_severity_with_nothing_measured_is_insufficient():
    result = drift.overall_severity(
        {
            "feature": "insufficient_data",
            "prediction": "insufficient_data",
            "performance": "insufficient_data",
        }
    )
    assert result == "insufficient_data"
