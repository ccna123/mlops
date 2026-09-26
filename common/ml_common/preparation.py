"""Which rows of a working copy become the train set and the test set.

ROW-wise work, like `rowops`, which it builds on: it must only ever be called
from the `prepare_dataset_for_train` stage (and the feedback pipeline), never
from a Pipeline, `features.py` or serving.

The selection is planned on a few light columns first, so the full rows of only
the chosen records need to be read afterwards (PCN-05). In order (02 3.4):

1. build the target (feedback records already carry theirs);
2. drop duplicate property ids BEFORE splitting, so one house can never sit in
   both the train set and the test set;
3. drop records without a target;
4. place every record in train, test or simulation by the version's split points;
5. when a row limit is asked for, sample that many train records at random with
   a fixed seed. The test set is never sampled, so every run on the same
   dataset version is scored on the same test set (NV-06).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import rowops, schema, splits
from .targets import TARGET_SOURCE, derive_target

_POSITION = "_position"


def light_columns(task_type: str, available: list[str]) -> list[str]:
    """Lists the columns needed to plan the split, among those the data has.

    Args:
        task_type: "regression" or "classification".
        available: the column names of the working copy.

    Returns:
        The id, the date columns, the source columns and the target source(s),
        restricted to what exists in `available`, in a fixed order.

    Example:
        light_columns("classification", raw.columns.tolist())
        # -> ["property_id", "listing_date", "condition"]  (for an upload)
    """
    wanted = [
        schema.ID_COLUMN,
        "listing_date",
        splits.SOURCE_COLUMN,
        splits.PREDICTED_AT_COLUMN,
        TARGET_SOURCE[task_type],
        schema.target_column(task_type),
    ]
    seen: list[str] = []
    for name in wanted:
        if name in available and name not in seen:
            seen.append(name)
    return seen


@dataclass
class RowPlan:
    """The rows the prepare stage keeps, as positions in the working copy.

    Example:
        plan = plan_rows(light, "regression", manifest["split_points"], 200_000, 42)
        plan.train_positions[:3]  # -> array([0, 5, 9])
        plan.counts["simulation_rows"]  # -> 19873
    """

    train_positions: np.ndarray
    test_positions: np.ndarray
    counts: dict = field(default_factory=dict)


def plan_rows(
    light: pd.DataFrame,
    task_type: str,
    split_points: dict,
    sample_rows: int | None,
    seed: int,
) -> RowPlan:
    """Decides which working-copy rows go to the train set and the test set.

    Args:
        light: the working copy's `light_columns`, one row per record, in file
            order. Its row positions are what the plan refers to.
        task_type: "regression" or "classification".
        split_points: the dataset version's manifest `split_points`.
        sample_rows: how many train records to keep, or None for all of them.
        seed: the random seed of the train sample.

    Returns:
        A `RowPlan` with sorted positions and the counts the stage reports:
        `dropped_duplicates`, `dropped_missing_target`, `train_available`,
        `simulation_rows`.

    Raises:
        ValueError: when `sample_rows` is not positive.

    Example:
        plan = plan_rows(light, "regression", split_points, 1000, 42)
        len(plan.train_positions)  # -> 1000
        len(plan.test_positions)   # -> the same whatever sample_rows is
    """
    if sample_rows is not None and sample_rows < 1:
        raise ValueError(f"sample_rows must be positive, got: {sample_rows}")
    frame = light.reset_index(drop=True)
    frame[_POSITION] = np.arange(len(frame))

    frame, dropped_duplicates = rowops.drop_duplicates(frame)
    frame[schema.target_column(task_type)] = derive_target(frame, task_type)
    frame, dropped_missing = rowops.drop_rows_missing_target(frame, task_type)

    assigned = splits.assign_split(frame, split_points)
    train = frame.loc[assigned == splits.SPLIT_TRAIN, _POSITION].to_numpy()
    test = frame.loc[assigned == splits.SPLIT_TEST, _POSITION].to_numpy()
    train_available = len(train)
    if sample_rows is not None and sample_rows < len(train):
        rng = np.random.default_rng(seed)
        train = rng.choice(train, size=sample_rows, replace=False)

    return RowPlan(
        train_positions=np.sort(train),
        test_positions=np.sort(test),
        counts={
            "dropped_duplicates": int(dropped_duplicates),
            "dropped_missing_target": int(dropped_missing),
            "train_available": int(train_available),
            "simulation_rows": int((assigned == splits.SPLIT_SIMULATION).sum()),
        },
    )
