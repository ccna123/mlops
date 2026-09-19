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

    Handles dirty type 2 (~0.6% of rows are duplicated). Returns
    (new df, dropped row count) so the `prepare_dataset_for_train` stage can log the count.
    """
    row_count_before = len(df)
    result = df.drop_duplicates(subset=[schema.ID_COLUMN], keep="first").reset_index(drop=True)
    return result, row_count_before - len(result)


def drop_rows_missing_target(df: pd.DataFrame, task_type: str) -> tuple[pd.DataFrame, int]:
    """Drops rows with no target value — they can't be trained on.

    Returns (new df, dropped row count).
    """
    target_column = schema.target_column(task_type)
    if target_column not in df.columns:
        raise KeyError(f"Missing target column {target_column!r} in DataFrame")
    row_count_before = len(df)
    result = df[df[target_column].notna()].reset_index(drop=True)
    return result, row_count_before - len(result)
