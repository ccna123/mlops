"""Prepare stage: row-level work and the train/test split. Nothing column-level.

Column cleaning deliberately does NOT happen here. It lives inside the sklearn
Pipeline so it ships with the model and runs identically at serving time. The
files this stage writes still hold raw column values.

The target is the one exception: it is not a feature, serving never sends one,
so building it here cannot drift from anything. Regression parses `sale_price`;
classification has no target column in the raw data at all — `needs_renovation`
is derived here from `condition`.
"""

from __future__ import annotations

import os
import sys

from ml_common import schema
from ml_common.rowops import drop_duplicates, drop_rows_missing_target
from ml_common.stageio import emit_result
from ml_common.storage import Storage, extracted_key, processed_key
from ml_common.targets import derive_target
from sklearn.model_selection import train_test_split

TEST_SIZE = 0.2
RANDOM_STATE = 42


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    force = os.environ.get("FORCE_REPROCESS", "false").strip().lower() == "true"
    storage = Storage.from_env()

    train_destination = processed_key(fingerprint, task_type, "train")
    test_destination = processed_key(fingerprint, task_type, "test")

    already_there = storage.exists(train_destination) and storage.exists(test_destination)
    if already_there and not force:
        train_rows = len(storage.read_parquet(train_destination))
        test_rows = len(storage.read_parquet(test_destination))
        print(f"cache hit for {fingerprint}, skipping", file=sys.stderr)
        emit_result({"skipped": True, "train_rows": train_rows, "test_rows": test_rows})
        return 0

    if already_there:
        print("cache present but FORCE_REPROCESS is set, rebuilding", file=sys.stderr)

    df = storage.read_parquet(extracted_key(fingerprint))
    print(f"read {len(df)} rows", file=sys.stderr)

    df, duplicate_count = drop_duplicates(df)
    print(f"dropped {duplicate_count} duplicate rows", file=sys.stderr)

    target = schema.target_column(task_type)
    df[target] = derive_target(df, task_type)

    df, missing_target_count = drop_rows_missing_target(df, task_type)
    print(f"dropped {missing_target_count} rows with an unusable target", file=sys.stderr)

    if task_type == "classification":
        # derive_target returns object dtype so it can carry nulls; once those
        # rows are gone, pin it to bool so the parquet schema is deterministic
        # and train does not receive an object column.
        df[target] = df[target].astype(bool)

    if len(df) < 2:
        print("FATAL: not enough usable rows to split", file=sys.stderr)
        return 1

    train_df, test_df = train_test_split(df, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    storage.write_parquet(train_df, train_destination)
    storage.write_parquet(test_df, test_destination)
    print(f"wrote {len(train_df)} train / {len(test_df)} test rows", file=sys.stderr)

    emit_result(
        {
            "skipped": False,
            "train_rows": len(train_df),
            "test_rows": len(test_df),
            "dropped_duplicates": int(duplicate_count),
            "dropped_missing_target": int(missing_target_count),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
