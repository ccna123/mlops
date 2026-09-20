"""The half of monitoring that does not need Evidently.

Reading the window, rebuilding the raw records, joining ground truth, and
deciding what counts as `ok`, `warning` or `high` are all plain pandas. They
live here rather than in the monitor stage for one reason: the severity
rules are the part most likely to be wrong, and here they run in the test
suite on a dev machine with no container and no Evidently.

The split is: this module DECIDES, and `stages/monitor/main.py` calls
Evidently and writes the files.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd

from .storage import ground_truth_prefix, inference_log_prefix


def days_in_window(end: datetime, window_hours: int) -> list[date]:
    """Lists the day partitions a time window touches.

    Args:
        end: the end of the window, timezone-aware and in UTC.
        window_hours: how many hours back the window reaches.

    Returns:
        Every date from the start of the window to `end`, in order. A window
        that reaches back across midnight returns more than one date, which
        is why this exists at all: the logs are partitioned by day, so a
        24-hour window almost always has to read two prefixes.

    Example:
        days_in_window(datetime(2026, 9, 20, 18, tzinfo=UTC), 6)
        # -> [date(2026, 9, 20)]

        days_in_window(datetime(2026, 9, 20, 9, tzinfo=UTC), 24)
        # -> [date(2026, 9, 19), date(2026, 9, 20)]
    """
    start = end - timedelta(hours=window_hours)
    days: list[date] = []
    cursor = start.date()
    while cursor <= end.date():
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _read_prefix_days(storage, prefix_builder, model_name: str, days: list[date]) -> pd.DataFrame:
    """Reads and concatenates every parquet part under one prefix per day.

    Args:
        storage: anything with `list_keys` and `read_parquet`.
        prefix_builder: a function taking (model_name, day) and returning a prefix.
        model_name: the registered model whose data is wanted.
        days: the day partitions to read.

    Returns:
        One DataFrame holding every part found, with a fresh index. A day
        with no files contributes nothing; no files at all returns an empty
        DataFrame rather than raising, because "nobody sent traffic" is a
        normal state, not a failure.
    """
    frames: list[pd.DataFrame] = []
    for day in days:
        for key in storage.list_keys(prefix_builder(model_name, day)):
            frames.append(storage.read_parquet(key))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_predictions(storage, model_name: str, end: datetime, window_hours: int) -> pd.DataFrame:
    """Reads every prediction served inside the window.

    Args:
        storage: a `Storage`, or anything with `list_keys` and `read_parquet`.
        model_name: the registered model that served them.
        end: the end of the window, timezone-aware UTC.
        window_hours: how far back to read.

    Returns:
        The inference log rows - request_id, timestamp, raw_input, prediction,
        model_name, model_version - concatenated across every part file of
        every day the window touches. Empty when there was no traffic.

    Example:
        predictions = load_predictions(storage, "house_price_regressor", now, 24)
        # -> 1,432 rows gathered from part files across two day partitions
    """
    days = days_in_window(end, window_hours)
    return _read_prefix_days(storage, inference_log_prefix, model_name, days)


def load_outcomes(storage, model_name: str, end: datetime, window_hours: int) -> pd.DataFrame:
    """Reads every ground-truth outcome reported for the window.

    Args:
        storage: a `Storage`, or anything with `list_keys` and `read_parquet`.
        model_name: the registered model the outcomes belong to.
        end: the end of the window, timezone-aware UTC.
        window_hours: how far back to read.

    Returns:
        The ground-truth rows - request_id, actual, received_at - or an empty
        DataFrame. Empty is the normal state early on: ground truth always
        arrives later than the prediction it describes.

    Example:
        outcomes = load_outcomes(storage, "house_price_regressor", now, 24)
        # -> often empty on the first run, which is not an error
    """
    days = days_in_window(end, window_hours)
    return _read_prefix_days(storage, ground_truth_prefix, model_name, days)


def decode_raw_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    """Rebuilds the served records from the JSON text in the inference log.

    Serving stores each record as `json.dumps(record)` in a single
    `raw_input` column, because a record's shape varies from call to call and
    parquet wants a fixed schema. Evidently needs real columns back.

    Args:
        frame: inference log rows carrying a `raw_input` column.

    Returns:
        A DataFrame of the decoded records, one row per input row, indexed
        positionally. Keys absent from a record become NaN, so two rows that
        carried different optional columns still line up. An empty input
        returns an empty DataFrame.

    Example:
        decode_raw_inputs(log)
        # -> columns city, bedrooms, list_price, ... exactly as callers sent
        #    them, still raw: "$450,000" is still a string here.
    """
    if len(frame) == 0:
        return pd.DataFrame()
    records = [json.loads(text) for text in frame["raw_input"]]
    return pd.DataFrame(records)


def join_outcomes(predictions: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Matches predictions to the outcomes that were later reported for them.

    Args:
        predictions: inference log rows, carrying `request_id` and `prediction`.
        outcomes: ground-truth rows, carrying `request_id` and `actual`.

    Returns:
        Only the rows where both sides exist - an inner join on `request_id`.
        Feedback for a prediction served before the window is dropped, and so
        is a prediction nobody has reported on yet. That second group is the
        normal case, and its size is what decides whether performance drift
        can be measured at all.

    Example:
        joined = join_outcomes(predictions, outcomes)
        # -> 137 rows out of 1,432 predictions; the other 1,295 have no
        #    outcome yet, which is why performance drift always lags.
    """
    if len(predictions) == 0 or len(outcomes) == 0:
        empty = predictions.iloc[0:0].copy()
        empty["actual"] = pd.Series(dtype="object")
        return empty
    return predictions.merge(outcomes[["request_id", "actual"]], on="request_id", how="inner")
