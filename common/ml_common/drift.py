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


def days_in_window(end: datetime, window_hours: float) -> list[date]:
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


def load_predictions(storage, model_name: str, end: datetime, window_hours: float) -> pd.DataFrame:
    """Reads every prediction served inside the window.

    Args:
        storage: a `Storage`, or anything with `list_keys` and `read_parquet`.
        model_name: the registered model that served them.
        end: the end of the window, timezone-aware UTC.
        window_hours: how far back to read.

    Returns:
        The inference log rows - request_id, timestamp, raw_input, prediction,
        model_name, model_version - filtered to `timestamp` inside
        [end - window_hours, end], across every part file of every day the
        window touches. Empty when there was no traffic.

        The day-partition read on its own is not enough: the log is
        partitioned by day, not by hour, so a `window_hours=1` run started
        minutes after an earlier run on the SAME day would otherwise read
        that earlier run's rows too - two batches sent an hour apart on the
        same day partition would silently mix. The `timestamp` column is
        what actually bounds the window; the day list only decides which
        part files are worth opening at all.

    Example:
        predictions = load_predictions(storage, "house_price_regressor", now, 24)
        # -> 1,432 rows gathered from part files across two day partitions

        # Two agent runs an hour apart, same day, MONITOR_WINDOW_HOURS=1:
        # the second run's load_predictions call excludes the first run's
        # rows even though both live under the same dt=... prefix.
    """
    days = days_in_window(end, window_hours)
    frame = _read_prefix_days(storage, inference_log_prefix, model_name, days)
    if len(frame) == 0:
        return frame
    start = end - timedelta(hours=window_hours)
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    in_window = (timestamps >= start) & (timestamps <= end)
    return frame[in_window].reset_index(drop=True)


def load_outcomes(storage, model_name: str, end: datetime, window_hours: float) -> pd.DataFrame:
    """Reads every ground-truth outcome reported for the window.

    Args:
        storage: a `Storage`, or anything with `list_keys` and `read_parquet`.
        model_name: the registered model the outcomes belong to.
        end: the end of the window, timezone-aware UTC.
        window_hours: how far back to read.

    Returns:
        The ground-truth rows - request_id, predicted_on, actual, model_name -
        or an empty DataFrame. Empty is the normal state early on: ground
        truth always arrives later than the prediction it describes.

        Unlike `load_predictions`, this is NOT further filtered by an actual
        timestamp - a ground-truth row carries no timestamp of its own, only
        the day it was filed under. That is fine: `join_outcomes` matches on
        `request_id`, and only outcomes whose request_id is in the
        already-window-filtered predictions survive the join, so an outcome
        for a different scenario's request never joins to this window's rows.

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

# Observed (fingerprint 1630bf27520bba7f, 500-row batches, task-11 live
# runs): scenario=none scored a drifted-columns share of 0.0909 (2 of 22
# compared columns). The 0.3 line above sits comfortably clear of that -
# not miscalibrated for BROAD drift. What it cannot see is drift
# CONCENTRATED into a few columns: see FEATURE_MAGNITUDE_WARNING below.
RMSE_WARNING_RATIO = 1.2
RMSE_HIGH_RATIO = 1.5

AUC_WARNING_DROP = 0.05
AUC_HIGH_DROP = 0.10

# Share dilutes concentrated drift. With 21 compared columns, 7 must cross
# their own threshold before FEATURE_WARNING_SHARE even fires. The
# market_shift scenario (city forced to a single value) concentrates ALL
# its drift into exactly 2 columns - city and zipcode - and measured a
# share of 2/21 = 0.0952, IDENTICAL to scenario=none's share, because
# zipcode (a high-cardinality categorical - thousands of distinct 5-digit
# codes) crosses its own 0.1 Jensen-Shannon threshold from sampling noise
# alone, in EVERY run, real drift or not: both the none and market_shift
# runs measured zipcode at 0.825054, to six decimal places identical
# (both used the default --seed 42 pool sample against the default
# REFERENCE_SEED=42 reference sample, so the underlying zipcode values
# were literally the same set in both runs).
#
# feature_margin_severity sums how far PAST its own threshold every
# compared column's drift score sits (value - threshold, negative when
# under), across every compared column. That sum is dominated by however
# many quiet columns sit comfortably under their own threshold - each one
# contributes a small negative term - so the 0.0 line below is calibrated
# against the CURRENT number of compared columns (21: run_drift_report
# subsets both frames to shared_numeric + shared_categorical before handing
# them to Evidently, so property_id no longer rides along - see
# run_drift_report in stages/monitor/main.py). Adding or removing a feature
# column shifts every future sum, so this constant would need recalibrating
# against fresh measurements if the compared column count changes again, not
# just trusted to keep separating the same way.
# zipcode's near-identical ~+0.725 excess contributes almost equally to both
# runs' sums and washes out of the COMPARISON, leaving the genuine
# difference: city's margin, which went from +0.001 (value 0.101 against
# threshold 0.1, barely over) in scenario=none to +0.675 (value 0.775
# against threshold 0.1, massively over) in market_shift.
#
# Observed sums across the 21 columns actually compared today (task-11
# market_shift addendum, same fingerprint/runs as above; the raw runs
# measured 22 columns because run_drift_report did not yet subset out
# property_id, whose own margin was a constant -0.05 in both runs - it is
# subtracted back out here analytically rather than re-measured):
#   scenario=none:  -0.2344  (was -0.2844 across 22 columns)
#   market_shift:   +0.4401  (was +0.3901 across 22 columns)
# A swing of 0.6745 across the zero crossing chosen below. Margin from the
# none observation to the line: 0.2344. Margin from the line to the
# market_shift observation: 0.4401. Both comfortable - this is not a
# threshold tuned to barely separate two samples.
#
# There is deliberately NO high-tier magnitude constant. Exactly one
# above-warning observation exists (market_shift, +0.4401) and inventing a
# "high" cutoff from a single data point is exactly the kind of guess this
# task exists to stop making - left undefined until a second real
# high-magnitude measurement exists to calibrate against.
#
# Tie-break: a sum of EXACTLY 0.0 reads as "warning" (feature_margin_severity
# uses >=, not >). Every other threshold in this module already resolves its
# own tie this way - feature_severity's 0.3 share, performance_severity's
# 1.2 rmse ratio and 0.05 auc drop are all ">=" into the worse band - and
# erring toward flagging is the right direction for a monitoring system.
FEATURE_MAGNITUDE_WARNING = 0.0


def feature_severity(drifted_share: float, margins: list[float] | None = None) -> str:
    """Grades feature drift from the share of columns Evidently flagged.

    Args:
        drifted_share: fraction of columns reported as drifted, 0.0 to 1.0.
        margins: optional - for every column Evidently compared,
            (observed drift value - that column's own detection threshold).
            None or empty runs the share-only grade exactly as before -
            every existing caller is unaffected. When supplied, the worse
            of the share-based grade and `feature_margin_severity(margins)`
            wins. This is what catches drift concentrated into a few
            columns, which the share path dilutes into invisibility - see
            the comment above FEATURE_MAGNITUDE_WARNING.

    Returns:
        "ok" below 0.3 share, "warning" from 0.3 through 0.5, "high" above
        0.5 - OR whatever `feature_margin_severity(margins)` grades, if
        that is worse.

    Example:
        feature_severity(0.1)   # -> "ok", a column or two moving is normal
        feature_severity(0.4)   # -> "warning"
        feature_severity(0.8)   # -> "high"

        # market_shift: share alone says "ok" (2/22 = 0.0909, same as a
        # clean run), but the magnitude of those 2 columns' drift tells a
        # different story:
        feature_severity(0.0909, margins=[0.3901])   # -> "warning"
    """
    if drifted_share > FEATURE_HIGH_SHARE:
        share_result = "high"
    elif drifted_share >= FEATURE_WARNING_SHARE:
        share_result = "warning"
    else:
        share_result = "ok"

    if not margins:
        return share_result

    magnitude_result = feature_margin_severity(margins)
    return max((share_result, magnitude_result), key=SEVERITIES.index)


def feature_margin_severity(margins: list[float]) -> str:
    """Grades feature drift from HOW FAR PAST threshold the compared columns sit.

    Where `feature_severity`'s share counts how many columns crossed their
    threshold, this sums by how much - across every compared column, not
    just the ones that crossed. That sum is robust to a single persistently
    noisy column (like a high-cardinality zipcode) dominating the picture:
    a column that scores the same in every run contributes the same
    constant amount to the sum in every run, and cancels out of any
    comparison between two runs. See FEATURE_MAGNITUDE_WARNING for the
    numbers this was calibrated against.

    Args:
        margins: (observed drift value - detection threshold) for every
            column Evidently compared. Positive means that column crossed
            its own threshold; negative means it did not.

    Returns:
        "warning" when the sum is at or above FEATURE_MAGNITUDE_WARNING,
        "ok" otherwise - including when margins is empty, the same safe
        default an empty share gets. There is no "high" tier - see the
        comment above FEATURE_MAGNITUDE_WARNING for why.

    Example:
        feature_margin_severity([-0.05, -0.02, 0.001, 0.725])  # -> "ok"
        # scenario=none: sums to -0.2844 over all 22 columns in the real run

        feature_margin_severity([-0.05, -0.02, 0.675, 0.725])  # -> "warning"
        # market_shift: sums to +0.3901 over all 22 columns in the real run
    """
    if not margins:
        return "ok"
    return "warning" if sum(margins) >= FEATURE_MAGNITUDE_WARNING else "ok"


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
