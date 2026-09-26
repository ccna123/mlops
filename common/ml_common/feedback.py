"""Turning served predictions that have ground truth into training data (CN-42).

Retraining on the same data teaches a new model exactly what the old one knew:
if the market moved, the new model is as wrong as the old. So every house that
was predicted AND whose real outcome came back becomes a feedback record in a
new dataset version, next to the data of the version it derives from.

In order (02 3.11):

1. join the prediction log and the ground truth of the chosen period on the
   request id; keep only predictions that got an outcome;
2. one feedback record per pair: the raw input exactly as it was sent, the
   outcome in the task's label column, record source "feedback" and the moment
   of the prediction; a house predicted several times keeps its latest;
3. refuse when fewer than `MIN_FEEDBACK_RECORDS` remain: the test set (the
   latest 20% of them) would be too small to trust;
4. new data = feedback records + the source version's data, minus the source
   records of the same houses (two records of one house with two prices would
   teach two contradicting labels);
5. split points: test = the latest 20% of the feedback records; train = all of
   the source's train and test plus the earlier feedback; simulation = the
   source's simulation set minus the houses that became feedback.

Like `rowops`, this drops and replaces rows: only the feedback stage calls it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd

from . import drift, schema, splits

MIN_FEEDBACK_RECORDS = 500
FEEDBACK_TEST_SHARE = 0.20
DEFAULT_PERIOD_DAYS = 30


class NotEnoughFeedbackError(Exception):
    """Raised when too few predictions have ground truth to build a version from.

    Example:
        raise NotEnoughFeedbackError("only 120 predictions have ground truth; 500 needed")
    """


def default_period(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The period used when the operator does not choose one: the last 30 days.

    Args:
        now: the end of the period; None reads the clock.

    Returns:
        `(start, end)`, timezone-aware UTC.

    Example:
        default_period(datetime(2026, 9, 26, tzinfo=UTC))
        # -> (datetime(2026, 8, 27, tzinfo=UTC), datetime(2026, 9, 26, tzinfo=UTC))
    """
    end = now or datetime.now(UTC)
    return end - timedelta(days=DEFAULT_PERIOD_DAYS), end


def matched_predictions(storage, model_name: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Reads the predictions of a period that have ground truth.

    Args:
        storage: a `Storage`.
        model_name: the registered model that served them.
        start: start of the period, timezone-aware UTC.
        end: end of the period, timezone-aware UTC.

    Returns:
        Prediction log rows (`request_id`, `timestamp`, `raw_input`, ...) with
        the observed `actual` added. Predictions without an outcome are left
        out.

    Example:
        matched_predictions(storage, "house_price_regressor", start, end)
        # -> 1,480 rows, each with its raw input and the price it sold for
    """
    hours = (end - start).total_seconds() / 3600
    predictions = drift.load_predictions(storage, model_name, end, hours)
    if len(predictions) == 0:
        return predictions
    outcomes = drift.load_outcomes(storage, model_name, end, hours)
    if len(outcomes) == 0:
        return predictions.iloc[0:0].assign(actual=pd.Series(dtype=object))
    return drift.join_outcomes(predictions, outcomes)


def _as_text(value: object) -> object:
    """Stores a value the way raw data stores everything: as text, or None.

    Args:
        value: any JSON value from a raw input.

    Returns:
        None for a missing value, the value's string form otherwise.

    Example:
        _as_text(3)      # -> "3"
        _as_text(None)   # -> None
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def build_feedback_records(matched: pd.DataFrame, task_type: str) -> pd.DataFrame:
    """Builds one feedback record per prediction that has ground truth.

    Args:
        matched: what `matched_predictions` returned.
        task_type: "regression" or "classification".

    Returns:
        Records with every raw column as text (the dataset's own convention),
        the outcome in the label column (`sale_price` or `needs_renovation`),
        `record_source` = "feedback" and `predicted_at`. A property predicted
        several times keeps only its latest prediction.

    Example:
        build_feedback_records(matched, "regression")["sale_price"].iloc[0]
        # -> "504000.0", the price the house really sold for
    """
    label = schema.target_column(task_type)
    rows = []
    for raw_input, actual, timestamp in zip(
        matched["raw_input"], matched["actual"], matched["timestamp"], strict=True
    ):
        record = {k: _as_text(v) for k, v in json.loads(raw_input).items()}
        record[label] = _as_text(bool(actual) if task_type == "classification" else actual)
        record[splits.SOURCE_COLUMN] = splits.SOURCE_FEEDBACK
        record[splits.PREDICTED_AT_COLUMN] = str(timestamp)
        rows.append(record)
    records = pd.DataFrame(rows)
    if len(records) == 0:
        return records
    order = records[splits.PREDICTED_AT_COLUMN].map(splits.to_moment)
    records = records.assign(_order=order).sort_values("_order", kind="stable")
    records = records.drop_duplicates(subset=[schema.ID_COLUMN], keep="last")
    return records.drop(columns="_order").reset_index(drop=True)


def merge_with_source(source: pd.DataFrame, records: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Puts feedback records in place of the source records of the same houses.

    Args:
        source: the source dataset version's data.
        records: `build_feedback_records` output.

    Returns:
        `(merged, replaced)`: the source minus houses that became feedback,
        followed by the feedback records, every column as text or None; and
        how many source records were replaced.

    Example:
        merged, replaced = merge_with_source(source, records)
        replaced  # -> 312
    """
    replaced_mask = source[schema.ID_COLUMN].astype(str).isin(
        set(records[schema.ID_COLUMN].astype(str))
    )
    kept = source[~replaced_mask]
    merged = pd.concat([kept, records], ignore_index=True, sort=False)
    merged = merged.astype(object).where(merged.notna(), None)
    return merged, int(replaced_mask.sum())


def feedback_split_points(source_manifest: dict, records: pd.DataFrame) -> dict:
    """Builds the split rules of the new version.

    Args:
        source_manifest: the source version's manifest.
        records: the feedback records (with `predicted_at`).

    Returns:
        `{"original": ..., "feedback": ...}`. Original records: everything
        before the source's T2 (its train AND test sets) and every undated one
        is train; from T2 on stays simulation. Feedback records: the latest
        `FEEDBACK_TEST_SHARE` by prediction time are test, the rest train, no
        simulation.

    Example:
        feedback_split_points(manifest, records)
        # -> {"original": {"t1": "2024-10-15", "t2": "2024-10-15",
        #                  "undated_test_share": 0.0},
        #     "feedback": {"t1": "2026-09-20T10:04:31.120000", "t2": None,
        #                  "undated_test_share": 0.0}}
    """
    source_t2 = source_manifest["split_points"][splits.SOURCE_ORIGINAL]["t2"]
    moments = sorted(records[splits.PREDICTED_AT_COLUMN].map(splits.to_moment))
    cut = moments[int(len(moments) * (1 - FEEDBACK_TEST_SHARE))]
    return {
        splits.SOURCE_ORIGINAL: {"t1": source_t2, "t2": source_t2, "undated_test_share": 0.0},
        splits.SOURCE_FEEDBACK: {"t1": cut.isoformat(), "t2": None, "undated_test_share": 0.0},
    }


def build_feedback_dataset(
    storage,
    *,
    task_type: str,
    model_name: str,
    source_version: str,
    start: datetime,
    end: datetime,
    new_version: str,
) -> dict:
    """Builds and stores a feedback dataset version.

    Args:
        storage: a `Storage`.
        task_type: "regression" or "classification".
        model_name: the model whose predictions are used.
        source_version: the dataset version to extend.
        start: start of the prediction period, timezone-aware UTC.
        end: end of the prediction period, timezone-aware UTC.
        new_version: the new version's name; must not exist.

    Returns:
        The new version's manifest, whose `lineage` records the source
        version, the period, how many feedback records were added and how
        many source records they replaced.

    Raises:
        DatasetVersionExistsError: when `new_version` is taken (CN-02).
        NotEnoughFeedbackError: when fewer than `MIN_FEEDBACK_RECORDS`
            predictions have ground truth.
        FileNotFoundError: when the source version does not exist.

    Example:
        build_feedback_dataset(storage, task_type="regression",
                               model_name="house_price_regressor", source_version="v1",
                               start=start, end=end, new_version="v1-fb1")
        # -> {"dataset_version": "v1-fb1", "lineage": {"feedback_records": 1480, ...}}
    """
    from .datasets import (
        DatasetVersionExistsError,
        dataset_exists,
        ensure_manifest,
        publish_frame,
    )
    from .storage import raw_key

    if dataset_exists(storage, new_version):
        raise DatasetVersionExistsError(f"dataset version {new_version!r} already exists")
    records = build_feedback_records(
        matched_predictions(storage, model_name, start, end), task_type
    )
    if len(records) < MIN_FEEDBACK_RECORDS:
        raise NotEnoughFeedbackError(
            f"only {len(records)} predictions have ground truth in the period; "
            f"{MIN_FEEDBACK_RECORDS} are needed for a test set worth trusting"
        )
    source_manifest = ensure_manifest(storage, source_version)
    source = storage.read_parquet(raw_key(source_version))
    merged, replaced = merge_with_source(source, records)
    manifest = {
        "dataset_version": new_version,
        "created_at": datetime.now(UTC).isoformat(),
        "row_count": int(len(merged)),
        "split_points": feedback_split_points(source_manifest, records),
        "lineage": {
            "source_version": source_version,
            "task_type": task_type,
            "model_name": model_name,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "feedback_records": int(len(records)),
            "replaced_records": replaced,
        },
    }
    publish_frame(storage, merged, new_version, manifest)
    return manifest
