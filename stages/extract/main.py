"""Extract stage: park the whole raw dataset as a working copy, and name this run's data.

Reads the raw dataset of a version from object storage and writes ALL of it,
as parquet, under its working copy ID. It never keeps only the first N rows:
the first rows of a file are not a random sample, and a file sorted by date or
by city would silently hand the model a skewed slice. The row limit is applied
later, by random sampling of the train set (prepare stage).

It also reads the version's split points (computing and storing them once for
versions created before split points existed) and computes the data ID that
names this run's prepared train and test sets.
"""

from __future__ import annotations

import os
import sys

from ml_common.datasets import ensure_manifest
from ml_common.fingerprint import compute_data_id, compute_working_copy_id
from ml_common.splits import RANDOM_SEED
from ml_common.stageio import emit_result
from ml_common.storage import Storage, extracted_key, raw_key


def read_sample_rows() -> int | None:
    """Reads the SAMPLE_ROWS limit for this run.

    Args:
        None. Reads the SAMPLE_ROWS environment variable.

    Returns:
        The number of train rows to sample, or None when the variable is unset
        or empty — both mean "use every train row". The value is part of the
        data ID, so a sampled run can never reuse a full run's train set.

    Raises:
        ValueError: when the variable holds something that is not a number.
            Falling back to "every row" would start a 2-million-row run on a
            machine that asked for 200k.

    Example:
        # SAMPLE_ROWS=200000  -> 200000
        # SAMPLE_ROWS=""      -> None
        # SAMPLE_ROWS="lots"  -> ValueError
    """
    raw_value = os.environ.get("SAMPLE_ROWS", "").strip()
    if not raw_value:
        return None
    return int(raw_value)


def main() -> int:
    """Writes the working copy and emits the IDs every later stage needs.

    Args:
        None. Reads DATASET_VERSION (default "v1"), SAMPLE_ROWS, and the MinIO
        variables `Storage.from_env` needs.

    Returns:
        0. Emits `working_copy_id`, `fingerprint` (the data ID), `row_count`,
        `sample_rows`, `seed` and `split_points` as the stage result. When the
        working copy already exists it is reused rather than rewritten.

    Raises:
        FileNotFoundError: when the raw object for that dataset version is not
            in storage. Nothing downstream can run, so the stage fails loudly
            rather than emitting IDs for data that does not exist.
    """
    dataset_version = os.environ.get("DATASET_VERSION", "v1")
    sample_rows = read_sample_rows()
    storage = Storage.from_env()

    source = raw_key(dataset_version)
    etag = storage.object_etag(source)
    working_copy_id = compute_working_copy_id(dataset_version, etag)
    data_id = compute_data_id(working_copy_id, sample_rows, RANDOM_SEED)
    manifest = ensure_manifest(storage, dataset_version)
    destination = extracted_key(working_copy_id)
    print(f"raw={source} etag={etag} sample_rows={sample_rows}", file=sys.stderr)

    if storage.exists(destination):
        _, row_count = storage.read_parquet_head(destination, 1)
        print(f"reusing existing {destination}", file=sys.stderr)
    else:
        df = storage.read_parquet(source)
        storage.write_parquet(df, destination)
        row_count = len(df)
        print(f"wrote {row_count} rows to {destination}", file=sys.stderr)

    emit_result(
        {
            "working_copy_id": working_copy_id,
            "fingerprint": data_id,
            "row_count": int(row_count),
            "sample_rows": sample_rows,
            "seed": RANDOM_SEED,
            "dataset_version": dataset_version,
            "split_points": manifest["split_points"],
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
