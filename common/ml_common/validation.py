"""Rules for the validate stage: measure the data, block only what is unusable.

This dataset is dirty on purpose — eight documented kinds of mess are the
exercise, not an incident. So validation counts everything and reports it, but
fails the run only when the data cannot be trained on at all.
"""

from __future__ import annotations

import pandas as pd

from . import schema
from .targets import TARGET_SOURCE

MAX_TARGET_MISSING_RATE = 0.5


def _missing_rate(series: pd.Series) -> float:
    """Measures how much of a column is missing.

    Args:
        series: the column to measure.

    Returns:
        The fraction of null values, between 0.0 and 1.0. An empty column
        returns 0.0: there is nothing missing from nothing, and the "no rows"
        rule in `validate_dataframe` is what catches an empty dataset.

    Example:
        _missing_rate(pd.Series([1, None, 3, None]))  # -> 0.5
        _missing_rate(pd.Series([], dtype=float))     # -> 0.0
    """
    if len(series) == 0:
        return 0.0
    return float(series.isna().mean())


def _out_of_bounds_count(series: pd.Series, spec: schema.ColumnSpec) -> int:
    """Counts values outside the schema bounds, ignoring anything non-numeric.

    Args:
        series: the raw column, still unparsed.
        spec: the column's schema entry, holding min_value and max_value.

    Returns:
        How many values fall outside the bounds. A column the schema gives no
        bounds returns 0. Values that cannot be read as numbers are not counted
        here: they are missing or mistyped, which the missing rate and the
        parsers already cover.

    Example:
        # bedrooms is declared min_value=0, max_value=20:
        _out_of_bounds_count(pd.Series([-1, 3, 999, "n/a", None]), COLUMNS["bedrooms"])
        # -> 2, counting only -1 and 999.
        # "n/a" and None are not counted: they are missing, not out of range.
    """
    if spec.min_value is None and spec.max_value is None:
        return 0
    numeric = pd.to_numeric(series, errors="coerce")
    outside = pd.Series(False, index=series.index)
    if spec.min_value is not None:
        outside |= numeric < spec.min_value
    if spec.max_value is not None:
        outside |= numeric > spec.max_value
    return int(outside.fillna(False).sum())


def validate_dataframe(df: pd.DataFrame, task_type: str) -> dict:
    """Measures a raw dataset and decides whether the run may continue.

    Args:
        df: the raw DataFrame, straight from `extracted/`.
        task_type: "regression" or "classification".

    Returns:
        A JSON-serializable report holding `ok`, `fatal` (the reasons the run
        cannot continue), `row_count`, `duplicate_rows` and `columns` — a
        missing_rate and out_of_bounds count per column. `ok` is False exactly
        when `fatal` is non-empty; everything else is measured and reported,
        never blocked on.

    Raises:
        ValueError: when task_type is not one of `schema.TASK_TYPES`.

    Example:
        report = validate_dataframe(df, "regression")
        # -> {"ok": True, "fatal": [], "row_count": 200000, "duplicate_rows": 1183,
        #     "columns": {"bedrooms": {"missing_rate": 0.031, "out_of_bounds": 87},
        #                 ...}}

        # 1183 duplicates and 87 impossible bedroom counts do NOT fail the run:
        # this dataset is dirty on purpose. Only these three fill `fatal` —
        # a missing schema column, zero rows, or a target source that is
        # missing in more than 50% of rows.
        if not report["ok"]:
            ...  # the validate stage exits 1 here
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    fatal: list[str] = []
    row_count = int(len(df))

    missing_columns = sorted(set(schema.COLUMNS) - set(df.columns))
    if missing_columns:
        fatal.append(f"missing columns required by the schema: {', '.join(missing_columns)}")

    if row_count == 0:
        fatal.append("the dataset has no rows")

    # Check the column the target is built FROM, not the target itself: validate
    # runs before prepare_dataset_for_train, so a derived target such as
    # needs_renovation does not exist yet and the rule would silently never run.
    target_source = TARGET_SOURCE[task_type]
    if target_source in df.columns and row_count > 0:
        missing_rate = _missing_rate(df[target_source])
        if missing_rate > MAX_TARGET_MISSING_RATE:
            fatal.append(
                f"target source {target_source!r} is missing in {missing_rate:.1%} of rows, "
                f"above the {MAX_TARGET_MISSING_RATE:.0%} limit"
            )

    columns: dict[str, dict] = {}
    for column_name, spec in schema.COLUMNS.items():
        if column_name not in df.columns:
            continue
        series = df[column_name]
        columns[column_name] = {
            "missing_rate": round(_missing_rate(series), 6),
            "out_of_bounds": _out_of_bounds_count(series, spec),
        }

    duplicate_rows = 0
    if schema.ID_COLUMN in df.columns:
        duplicate_rows = int(df[schema.ID_COLUMN].duplicated().sum())

    return {
        "ok": not fatal,
        "fatal": fatal,
        "row_count": row_count,
        "duplicate_rows": duplicate_rows,
        "columns": columns,
    }
