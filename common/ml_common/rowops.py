"""ROW-wise operations — only ever called from the `prepare_dataset_for_train` stage.

This file is deliberately kept separate from `cleaning.py`: the functions
here drop rows, so they must NEVER be placed in a sklearn Pipeline. Serving
calls /predict with a single record; a row-dropping step would return an
empty DataFrame and crash serving.

The file boundary itself is the safeguard — nobody imports this by mistake.
"""

from __future__ import annotations

import pandas as pd

from ml_common import schema


def drop_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drops rows with a duplicate `property_id`, keeping the first one.

    Handles dirty type 2 (~0.6% of rows are duplicated).

    Args:
        df: the DataFrame to deduplicate. Left untouched; a new frame is returned.

    Returns:
        A tuple of (deduplicated DataFrame with a fresh index, number of rows
        dropped). The `prepare_dataset_for_train` stage logs that count.

    Example:
        df = pd.DataFrame({"property_id": ["p1", "p2", "p1"], "city": [...]})
        result, dropped = drop_duplicates(df)
        # -> len(result) == 2, dropped == 1
        # The FIRST "p1" row is the one kept.
    """
    row_count_before = len(df)
    result = df.drop_duplicates(subset=[schema.ID_COLUMN], keep="first").reset_index(drop=True)
    return result, row_count_before - len(result)


def drop_rows_missing_target(df: pd.DataFrame, task_type: str) -> tuple[pd.DataFrame, int]:
    """Drops rows with no target value — they cannot be trained on.

    Args:
        df: a DataFrame whose target column has already been built by
            `targets.derive_target`. Left untouched; a new frame is returned.
        task_type: "regression" or "classification"; picks which column is the target.

    Returns:
        A tuple of (DataFrame with a fresh index holding only rows that have a
        target, number of rows dropped).

    Raises:
        KeyError: when the target column is absent. Returning an empty frame
            instead would look like empty data rather than a missing step.

    Example:
        # Called right after derive_target has filled the column:
        df["sale_price"] = derive_target(df, "regression")
        df, dropped = drop_rows_missing_target(df, "regression")
        # -> dropped counts the rows whose price could not be parsed at all

        # NEVER call this from a Pipeline or from serving: one record with an
        # unparseable target would come back as an empty frame.
    """
    target_column = schema.target_column(task_type)
    if target_column not in df.columns:
        raise KeyError(f"Missing target column {target_column!r} in DataFrame")
    row_count_before = len(df)
    result = df[df[target_column].notna()].reset_index(drop=True)
    return result, row_count_before - len(result)
