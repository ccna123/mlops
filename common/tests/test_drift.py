"""Tests for the pure-pandas half of monitoring.

Nothing here imports Evidently: that is the whole reason the severity rules
and the window handling live in common/ instead of in the monitor stage.
"""

import json
from datetime import UTC, date, datetime

import pandas as pd

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
            {"request_id": ["r1"], "prediction": [1.0]}
        ),
        "inference-log/m/dt=2026-09-20/part-b.parquet": pd.DataFrame(
            {"request_id": ["r2"], "prediction": [2.0]}
        ),
    }
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)

    result = drift.load_predictions(FakeStorage(frames), "m", end, 6)

    assert sorted(result["request_id"].tolist()) == ["r1", "r2"]


def test_load_predictions_reads_both_days_when_the_window_spans_midnight():
    frames = {
        "inference-log/m/dt=2026-09-19/part-a.parquet": pd.DataFrame(
            {"request_id": ["yesterday"], "prediction": [1.0]}
        ),
        "inference-log/m/dt=2026-09-20/part-b.parquet": pd.DataFrame(
            {"request_id": ["today"], "prediction": [2.0]}
        ),
    }
    end = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)

    result = drift.load_predictions(FakeStorage(frames), "m", end, 24)

    assert sorted(result["request_id"].tolist()) == ["today", "yesterday"]


def test_load_predictions_with_no_traffic_returns_empty_frame():
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    result = drift.load_predictions(FakeStorage({}), "m", end, 6)
    assert len(result) == 0


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
            {"request_id": ["r1"], "prediction": [1.0]}
        ),
    }
    end = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)

    # 2026-09-19 has no traffic at all; that is silence, not an error.
    result = drift.load_predictions(FakeStorage(frames), "m", end, 24)

    assert result["request_id"].tolist() == ["r1"]
