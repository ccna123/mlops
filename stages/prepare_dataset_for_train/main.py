"""Prepare stage: row-level work and the time-based split. Nothing column-level.

Column cleaning deliberately does NOT happen here. It lives inside the sklearn
Pipeline so it ships with the model and runs identically at serving time. The
files this stage writes still hold raw column values.

The target is the one exception: it is not a feature, serving never sends one,
so building it here cannot drift from anything.

Which rows go where is planned by `ml_common.preparation` on a few light
columns; only the chosen rows are then read in full (PCN-05). The simulation
set is never written here: it belongs to the simulation agent alone.
"""

from __future__ import annotations

import os
import sys

from ml_common import preparation, schema
from ml_common.datasets import read_manifest
from ml_common.splits import RANDOM_SEED
from ml_common.stageio import emit_result
from ml_common.storage import Storage, extracted_key, processed_key
from ml_common.targets import derive_target


def read_sample_rows() -> int | None:
    """Reads how many train rows this run samples.

    Args:
        None. Reads the SAMPLE_ROWS environment variable.

    Returns:
        The number, or None when unset or empty (every train row).

    Raises:
        ValueError: when the value is not a number.

    Example:
        # SAMPLE_ROWS=200000 -> 200000; SAMPLE_ROWS="" -> None
    """
    raw_value = os.environ.get("SAMPLE_ROWS", "").strip()
    return int(raw_value) if raw_value else None


def main() -> int:
    """Builds the target, splits by time, samples the train set, and writes both sets.

    Args:
        None. Reads WORKING_COPY_ID, FINGERPRINT (the data ID the output is
        stored under), DATASET_VERSION, TASK_TYPE, SAMPLE_ROWS and
        FORCE_REPROCESS ("true" rebuilds even on a cache hit), plus the MinIO
        variables `Storage.from_env` needs.

    Returns:
        0 on success, 1 when the train set or the test set comes out empty and
        there is nothing to train or score on. The stage result carries
        `skipped`, `train_rows` and `test_rows`, and on a real run also the
        counts `preparation.plan_rows` reports.

    Raises:
        KeyError: when a required variable is unset, or when the column the
            target is built from is missing.
        FileNotFoundError: when the working copy or the manifest is missing.
    """
    working_copy_id = os.environ["WORKING_COPY_ID"]
    data_id = os.environ["FINGERPRINT"]
    dataset_version = os.environ["DATASET_VERSION"]
    task_type = os.environ["TASK_TYPE"]
    sample_rows = read_sample_rows()
    force = os.environ.get("FORCE_REPROCESS", "false").strip().lower() == "true"
    storage = Storage.from_env()

    train_destination = processed_key(data_id, task_type, "train")
    test_destination = processed_key(data_id, task_type, "test")

    already_there = storage.exists(train_destination) and storage.exists(test_destination)
    if already_there and not force:
        _, train_rows = storage.read_parquet_head(train_destination, 1)
        _, test_rows = storage.read_parquet_head(test_destination, 1)
        print(f"cache hit for {data_id}, skipping", file=sys.stderr)
        emit_result({"skipped": True, "train_rows": train_rows, "test_rows": test_rows})
        return 0
    if already_there:
        print("cache present but FORCE_REPROCESS is set, rebuilding", file=sys.stderr)

    source = extracted_key(working_copy_id)
    header, total = storage.read_parquet_head(source, 1)
    light = storage.read_parquet(
        source, columns=preparation.light_columns(task_type, header.columns.tolist())
    )
    manifest = read_manifest(storage, dataset_version)
    plan = preparation.plan_rows(
        light, task_type, manifest["split_points"], sample_rows, RANDOM_SEED
    )
    del light
    print(f"read {total} rows; plan {plan.counts}", file=sys.stderr)

    if len(plan.train_positions) == 0 or len(plan.test_positions) == 0:
        print("FATAL: the train set or the test set is empty", file=sys.stderr)
        return 1

    target = schema.target_column(task_type)
    for positions, destination in (
        (plan.train_positions, train_destination),
        (plan.test_positions, test_destination),
    ):
        frame = storage.read_parquet_rows(source, positions)
        frame[target] = derive_target(frame, task_type)
        if task_type == "classification":
            # derive_target returns object dtype so it can carry nulls; every
            # row here has a target, so pin it to bool for a stable schema.
            frame[target] = frame[target].astype(bool)
        storage.write_parquet(frame, destination)

    print(
        f"wrote {len(plan.train_positions)} train / {len(plan.test_positions)} test rows",
        file=sys.stderr,
    )
    emit_result(
        {
            "skipped": False,
            "train_rows": int(len(plan.train_positions)),
            "test_rows": int(len(plan.test_positions)),
            **plan.counts,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
