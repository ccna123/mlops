"""How a dataset version is cut into train, test and simulation sets by time.

A model is deployed to predict houses listed AFTER everything it learned from,
so the test set has to be later than the train set too. A random split lets the
model learn the price level of the very months it is tested on, which makes the
test score look better than live use ever will (temporal leakage).

The split points are computed ONCE, when a dataset version is created, and
stored in its manifest. They do not depend on how many rows a run trains on, so
every run on the same dataset version is scored on the same test set.

Records carry a source. Original records sit on the time axis by their listing
date; feedback records (built from served predictions, see `feedback.py`) sit on
it by the moment they were predicted. Each source has its own split rule in the
manifest, because a feedback dataset version cuts its two sources differently.

This module decides which set a record belongs to. Dropping and sampling rows
is `rowops` territory and happens in the prepare stage only.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

import pandas as pd

from . import parsers, schema

SOURCE_COLUMN = "record_source"
PREDICTED_AT_COLUMN = "predicted_at"
SOURCE_ORIGINAL = "original"
SOURCE_FEEDBACK = "feedback"

SPLIT_TRAIN = "train"
SPLIT_TEST = "test"
SPLIT_SIMULATION = "simulation"

SIMULATION_TARGET_ROWS = 20_000
SIMULATION_MAX_SHARE = 0.10
TEST_SHARE = 0.20
UNDATED_TEST_SHARE = 0.20

RANDOM_SEED = 42

_HASH_BUCKETS = 10_000


def parse_dates(values: pd.Series) -> list[date | None]:
    """Parses a column of raw listing dates with the cleaning code's own rules.

    Parses each distinct value once: a 2-million-row column holds a few
    thousand distinct days, so this is far faster than parsing every row.

    Args:
        values: raw values, any of the three formats the dataset mixes.

    Returns:
        One `date` or None per input value, in order. None for anything the
        parser cannot read: a date is never guessed.

    Example:
        parse_dates(pd.Series(["2023-07-15", "07/15/2023", "15/07/2023"]))
        # -> [date(2023, 7, 15), date(2023, 7, 15), None]
    """
    # NaN is not equal to itself, so it cannot be a lookup key; None can.
    cleaned = values.astype(object).where(values.notna(), None)
    lookup = {value: parsers.parse_date(value) for value in pd.unique(cleaned)}
    return [lookup[value] for value in cleaned]


def record_sources(frame: pd.DataFrame) -> pd.Series:
    """Tells, per record, whether it is original data or a feedback record.

    Args:
        frame: a dataset frame. Uploaded data has no source column at all.

    Returns:
        A Series with the frame's index holding `SOURCE_ORIGINAL` or
        `SOURCE_FEEDBACK`. A missing column or a missing value means original.

    Example:
        record_sources(pd.DataFrame({"property_id": ["p1"]}))  # -> ["original"]
    """
    if SOURCE_COLUMN not in frame.columns:
        return pd.Series(SOURCE_ORIGINAL, index=frame.index, dtype=object)
    return frame[SOURCE_COLUMN].where(frame[SOURCE_COLUMN].notna(), SOURCE_ORIGINAL)


def _predicted_day(value: object) -> date | None:
    """Reads the day part of a stored prediction timestamp.

    Args:
        value: an ISO timestamp string, a datetime/Timestamp, or missing.

    Returns:
        The UTC day, or None when the value is missing or unreadable.

    Example:
        _predicted_day("2026-09-20T23:30:00+00:00")  # -> date(2026, 9, 20)
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(UTC)
    return stamp.date()


def event_dates(frame: pd.DataFrame) -> pd.Series:
    """Places every record on the time axis the split is made along.

    Args:
        frame: a dataset frame with `listing_date`, and for feedback records
            `predicted_at`.

    Returns:
        A Series with the frame's index holding a `date` or None. Original
        records use their listing date; feedback records use the day they were
        predicted, which is when the house actually entered the system.

    Example:
        event_dates(pd.DataFrame({"property_id": ["p1"], "listing_date": ["07/15/2023"]}))
        # -> [date(2023, 7, 15)]
    """
    listing = (
        parse_dates(frame["listing_date"]) if "listing_date" in frame.columns
        else [None] * len(frame)
    )
    result = pd.Series(listing, index=frame.index, dtype=object)
    sources = record_sources(frame)
    feedback = sources == SOURCE_FEEDBACK
    if feedback.any():
        if PREDICTED_AT_COLUMN not in frame.columns:
            raise ValueError(f"feedback records need a {PREDICTED_AT_COLUMN!r} column")
        result[feedback] = [_predicted_day(v) for v in frame.loc[feedback, PREDICTED_AT_COLUMN]]
    return result


def to_moment(value: object) -> pd.Timestamp | None:
    """Reads a split point or a prediction time as a naive UTC timestamp.

    Args:
        value: an ISO date ("2021-01-01", read as midnight), an ISO timestamp
            with or without an offset, a date/datetime, or missing.

    Returns:
        A timezone-naive UTC `pd.Timestamp`, or None when missing or unreadable.

    Example:
        to_moment("2026-09-20T23:30:00+02:00")  # -> Timestamp("2026-09-20 21:30:00")
        to_moment("2021-01-01")                 # -> Timestamp("2021-01-01 00:00:00")
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(UTC).tz_localize(None)
    return stamp


def event_moments(frame: pd.DataFrame) -> pd.Series:
    """Places every record on the time axis at the finest grain its source has.

    Original records only have a listing DAY, placed at midnight. Feedback
    records keep the exact prediction time: the simulation agent sends a whole
    batch within minutes, so a day-grained axis could not cut its latest 20%
    from the rest.

    Args:
        frame: a dataset frame with `listing_date`, and for feedback records
            `predicted_at`.

    Returns:
        A Series with the frame's index holding a naive UTC `pd.Timestamp` or
        None.

    Example:
        event_moments(frame)  # -> [Timestamp("2023-07-15"), Timestamp("2026-09-20 10:04:31")]
    """
    days = event_dates(frame)
    result = pd.Series(
        [None if d is None else pd.Timestamp(d) for d in days], index=frame.index, dtype=object
    )
    feedback = record_sources(frame) == SOURCE_FEEDBACK
    if feedback.any():
        result[feedback] = [to_moment(v) for v in frame.loc[feedback, PREDICTED_AT_COLUMN]]
    return result


def compute_split_points(dates: pd.Series) -> dict:
    """Chooses T1 and T2 for a set of dated records.

    T2 leaves about `SIMULATION_TARGET_ROWS` records on or after it, never more
    than `SIMULATION_MAX_SHARE` of the dated records. T1 leaves about
    `TEST_SHARE` of the records before T2 on or after it. Records sharing a
    boundary day all land on the later side, so the counts are approximate.

    Args:
        dates: one `date` or None per record. None is ignored: an undated
            record cannot move a boundary on a time axis it is not on.

    Returns:
        A split rule `{"t1": iso date, "t2": iso date, "undated_test_share":
        UNDATED_TEST_SHARE}`, ready to go into a manifest as it is.

    Raises:
        ValueError: when no record has a date.

    Example:
        compute_split_points(pd.Series([date(2020, 1, 1) + timedelta(days=i)
                                        for i in range(1000)]))
        # -> {"t1": "2021-12-21", "t2": "2022-06-19", "undated_test_share": 0.2}
        #    720 train, 180 test, 100 simulation (the 10% cap wins over 20,000)
    """
    dated = sorted(d for d in dates if d is not None)
    if not dated:
        raise ValueError("cannot place split points: no record has a listing date")
    count = len(dated)
    simulation_rows = min(SIMULATION_TARGET_ROWS, int(count * SIMULATION_MAX_SHARE))
    if simulation_rows > 0:
        t2 = dated[count - simulation_rows]
    else:
        t2 = date.fromordinal(dated[-1].toordinal() + 1)
    before_t2 = [d for d in dated if d < t2]
    if before_t2:
        t1 = before_t2[int(len(before_t2) * (1 - TEST_SHARE))]
    else:
        t1 = t2
    return {"t1": t1.isoformat(), "t2": t2.isoformat(), "undated_test_share": UNDATED_TEST_SHARE}


def _hash_share(property_id: object) -> float:
    """Maps a property id to a fixed number in [0, 1).

    A hash of the id, not Python's `hash()`, which changes between processes.

    Args:
        property_id: the id, any type; its string form is hashed.

    Returns:
        The same float for the same id, on every machine and every run.

    Example:
        _hash_share("p1") == _hash_share("p1")  # -> True, always
    """
    digest = hashlib.md5(str(property_id).encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % _HASH_BUCKETS) / _HASH_BUCKETS


def assign_split(frame: pd.DataFrame, split_points: dict) -> pd.Series:
    """Tells which set each record belongs to.

    Dated records: before T1 train, from T1 to before T2 test, from T2 on
    simulation (a null T2 means no simulation set). Undated records go to train
    or test by a fixed hash of `property_id`, `undated_test_share` of them to
    test, and never to simulation. Nothing is dropped.

    Args:
        frame: a dataset frame with `property_id` and `listing_date`.
        split_points: the manifest's `split_points`: one rule per record source
            present in the frame. `t1`/`t2` are ISO dates or ISO timestamps
            (feedback rules cut by prediction time, see `event_moments`).

    Returns:
        A Series with the frame's index holding "train", "test" or "simulation".

    Raises:
        ValueError: when the frame holds a record source that has no rule.

    Example:
        rules = {"original": {"t1": "2021-01-01", "t2": "2022-01-01",
                              "undated_test_share": 0.2}}
        assign_split(pd.DataFrame({"property_id": ["a", "b", "c"],
                                   "listing_date": ["2020-05-01", "2021-05-01",
                                                    "2023-01-01"]}), rules)
        # -> ["train", "test", "simulation"]
    """
    moments = event_moments(frame)
    sources = record_sources(frame)
    result = pd.Series(SPLIT_TRAIN, index=frame.index, dtype=object)
    for source in pd.unique(sources):
        if source not in split_points:
            raise ValueError(f"no split rule for record source {source!r}")
        rule = split_points[source]
        t1 = to_moment(rule["t1"])
        t2 = to_moment(rule.get("t2"))
        undated_share = float(rule.get("undated_test_share", UNDATED_TEST_SHARE))
        mask = sources == source
        labels = []
        for property_id, moment in zip(
            frame.loc[mask, schema.ID_COLUMN], moments[mask], strict=True
        ):
            if moment is None:
                labels.append(SPLIT_TEST if _hash_share(property_id) < undated_share
                              else SPLIT_TRAIN)
            elif moment < t1:
                labels.append(SPLIT_TRAIN)
            elif t2 is None or moment < t2:
                labels.append(SPLIT_TEST)
            else:
                labels.append(SPLIT_SIMULATION)
        result[mask] = labels
    return result


def build_manifest(dataset_version: str, listing_dates: pd.Series, row_count: int) -> dict:
    """Builds the manifest of a newly uploaded dataset version.

    Args:
        dataset_version: the version name.
        listing_dates: the raw `listing_date` column of the whole dataset.
        row_count: how many records the version holds.

    Returns:
        `{"dataset_version", "created_at", "row_count", "split_points",
        "lineage"}`. `split_points` has one rule, for original records.
        `lineage` is None: an upload comes from nowhere inside the system.

    Raises:
        ValueError: when no record has a readable listing date.

    Example:
        build_manifest("v2", raw["listing_date"], len(raw))
        # -> {"dataset_version": "v2", "row_count": 2012000,
        #     "split_points": {"original": {"t1": ..., "t2": ...,
        #                                   "undated_test_share": 0.2}},
        #     "created_at": "2026-09-26T08:00:00+00:00", "lineage": None}
    """
    rule = compute_split_points(pd.Series(parse_dates(listing_dates), dtype=object))
    return {
        "dataset_version": dataset_version,
        "created_at": datetime.now(UTC).isoformat(),
        "row_count": int(row_count),
        "split_points": {SOURCE_ORIGINAL: rule},
        "lineage": None,
    }


def training_order(frame: pd.DataFrame) -> tuple[pd.Index, int]:
    """Orders records for time-respecting cross-validation and threshold choice.

    Args:
        frame: a train set, with the columns `event_moments` reads.

    Returns:
        `(index, undated_rows)`: the frame's index labels with every undated
        record first (in file order), then the dated ones from oldest to
        newest; and how many undated records lead. Reorder with
        `frame.loc[index]`.

    Example:
        order, undated = training_order(train_df)
        train_df = train_df.loc[order]
        cv = TimeOrderedSplit(5, undated_rows=undated)
    """
    moments = event_moments(frame)
    undated = moments.map(lambda m: m is None)
    dated = moments[~undated].astype("datetime64[ns]").sort_values(kind="stable")
    return frame.index[undated.to_numpy()].append(dated.index), int(undated.sum())
