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


SEVERITIES = ("ok", "warning", "high")

# Performance drift has a third state the other two do not. Ground truth
# always arrives later than the prediction it describes, so early on there is
# simply nothing to measure. Reporting "ok" then would put a green badge on a
# dashboard when the truthful answer is "nobody has checked yet".
INSUFFICIENT = "insufficient_data"

MIN_GROUND_TRUTH = 50

FEATURE_WARNING_SHARE = 0.3
FEATURE_HIGH_SHARE = 0.5

RMSE_WARNING_RATIO = 1.2
RMSE_HIGH_RATIO = 1.5

AUC_WARNING_DROP = 0.05
AUC_HIGH_DROP = 0.10


def feature_severity(drifted_share: float) -> str:
    """Grades feature drift from the share of columns Evidently flagged.

    Args:
        drifted_share: fraction of columns reported as drifted, 0.0 to 1.0.

    Returns:
        "ok" below 0.3, "warning" from 0.3 through 0.5, "high" above 0.5.

    Example:
        feature_severity(0.1)   # -> "ok", a column or two moving is normal
        feature_severity(0.4)   # -> "warning"
        feature_severity(0.8)   # -> "high"

        # These numbers are a starting point, not a conclusion. Calibrate
        # them against a scenario=none run: if no-drift traffic already
        # scores 0.25, the 0.3 line is far too close.
    """
    if drifted_share > FEATURE_HIGH_SHARE:
        return "high"
    if drifted_share >= FEATURE_WARNING_SHARE:
        return "warning"
    return "ok"


def prediction_severity(drifted: bool) -> str:
    """Grades prediction drift, which is a single column and so a yes or no.

    Args:
        drifted: whether Evidently flagged the prediction column.

    Returns:
        "high" when it drifted, "ok" otherwise. There is no middle grade:
        one column cannot be partly drifted, and the model's own output
        shifting is worth looking at whenever it happens.

    Example:
        prediction_severity(True)   # -> "high"
        prediction_severity(False)  # -> "ok"
    """
    return "high" if drifted else "ok"


def performance_severity(task_type: str, current: dict, train: dict, n_joined: int) -> str:
    """Grades how far real accuracy has fallen from what training measured.

    Args:
        task_type: "regression" or "classification".
        current: metrics computed over the rows that have ground truth.
        train: the metrics logged by the train stage for this model version.
        n_joined: how many rows had ground truth. Below MIN_GROUND_TRUTH the
            metric is too noisy to act on.

    Returns:
        "insufficient_data" when n_joined is below the floor. Otherwise for
        regression, the rmse ratio: "ok" below 1.2x, "warning" to 1.5x,
        "high" above. For classification, the auc drop: "ok" under 0.05,
        "warning" to 0.10, "high" beyond. A model doing BETTER than at
        training is "ok", never worse.

    Raises:
        KeyError: when the metric a task needs is missing from either dict.
            Guessing would report a verdict nobody measured.

    Example:
        performance_severity("regression", {"rmse": 41000}, {"rmse": 41000}, 500)
        # -> "ok"

        performance_severity("regression", {"rmse": 70000}, {"rmse": 41000}, 500)
        # -> "high", predictions are off by 70% more than they were

        performance_severity("regression", {"rmse": 41000}, {"rmse": 41000}, 10)
        # -> "insufficient_data", NOT "ok" - 10 rows decides nothing
    """
    if n_joined < MIN_GROUND_TRUTH:
        return INSUFFICIENT

    if task_type == "regression":
        ratio = current["rmse"] / train["rmse"]
        if ratio > RMSE_HIGH_RATIO:
            return "high"
        if ratio >= RMSE_WARNING_RATIO:
            return "warning"
        return "ok"

    drop = train["auc"] - current["auc"]
    if drop >= AUC_HIGH_DROP:
        return "high"
    if drop >= AUC_WARNING_DROP:
        return "warning"
    return "ok"


def overall_severity(parts: dict) -> str:
    """Reduces the three drift verdicts to the one a dashboard shows.

    Args:
        parts: the per-type verdicts, e.g.
            {"feature": "ok", "prediction": "ok", "performance": "high"}.

    Returns:
        The worst of the measured verdicts. `insufficient_data` is skipped
        rather than counted: something unmeasured must not drag the badge up,
        and must not hold it down either. When nothing at all was measured,
        the answer is `insufficient_data`, because "ok" would claim a check
        that never happened.

    Example:
        overall_severity({"feature": "warning", "prediction": "high", "performance": "ok"})
        # -> "high"

        overall_severity({"feature": "ok", "prediction": "ok",
                          "performance": "insufficient_data"})
        # -> "ok", feature and prediction really were measured and were fine

        overall_severity({"feature": "insufficient_data",
                          "prediction": "insufficient_data",
                          "performance": "insufficient_data"})
        # -> "insufficient_data"
    """
    measured = [value for value in parts.values() if value in SEVERITIES]
    if not measured:
        return INSUFFICIENT
    return max(measured, key=SEVERITIES.index)
