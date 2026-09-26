"""Seeds the raw dataset into MinIO. Run once, by hand, from the repo root.

The pipeline's `extract` stage reads only from object storage, the way a real
system does: raw data is delivered by something upstream, not produced by the
pipeline itself. This script is that upstream delivery, done by hand.
"""

from __future__ import annotations

import argparse
import os
import tempfile

from ml_common.datasets import DatasetVersionExistsError, dataset_exists, publish_dataset
from ml_common.rawdata import csv_to_parquet
from ml_common.storage import Storage, raw_key

DEFAULT_SOURCE = "house_pricing_dirty.csv"


def parse_args() -> argparse.Namespace:
    """Reads the command line.

    Args:
        None. Parses sys.argv.

    Returns:
        A namespace with `source` (the local CSV, default
        "house_pricing_dirty.csv"), `version` (the dataset version to write
        under, default "v1") and `limit` (stop after this many rows, or None
        for all of them).

    Example:
        # python scripts/seed_raw_data.py
        # -> source="house_pricing_dirty.csv", version="v1", limit=None

        # python scripts/seed_raw_data.py --limit 200000 --version v2
        # -> a smaller v2 dataset, useful when disk space is short
    """
    parser = argparse.ArgumentParser(description="Upload the raw CSV to object storage.")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="local CSV to upload")
    parser.add_argument("--version", default="v1", help="dataset version to write under")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many rows")
    return parser.parse_args()


def main() -> int:
    r"""Converts the CSV to parquet and uploads it as the raw dataset.

    Args:
        None. Takes its settings from the command line, and the MinIO
        variables `Storage.from_env` needs from the environment.

    Returns:
        0 on success, 1 when the dataset version already exists: versions are
        never overwritten, so seeding twice is refused rather than repeated.
        The split points are computed from the whole file and written to the
        version's manifest, exactly as an upload through the API does. The
        parquet file is built in a temporary directory that is removed
        on the way out, so nothing large is left behind on a disk that is
        already nearly full.

    Raises:
        SystemExit: when the source CSV is not where it was expected — almost
            always because the script was run from somewhere other than the
            repo root.

    Example:
        # Run once, by hand, with the stack up:
        #   .venv\Scripts\python.exe scripts\seed_raw_data.py
        # -> Converting house_pricing_dirty.csv -> parquet
        #    ... 200,000 rows
        #    Uploading 118.4 MB to raw/v1/data.parquet
        #    Seeded 2,000,000 rows to raw/v1/data.parquet
    """
    args = parse_args()
    if not os.path.isfile(args.source):
        raise SystemExit(f"Source CSV not found: {args.source}. Run this from the repo root.")

    storage = Storage.from_env()
    key = raw_key(args.version)
    if dataset_exists(storage, args.version):
        print(f"Dataset version {args.version} already exists; versions are never overwritten.")
        return 1

    with tempfile.TemporaryDirectory() as workdir:
        local_parquet = os.path.join(workdir, "data.parquet")
        print(f"Converting {args.source} -> parquet")
        row_count = csv_to_parquet(
            args.source,
            local_parquet,
            args.limit,
            on_chunk=lambda written: print(f"  ... {written:,} rows"),
        )
        size_mb = os.path.getsize(local_parquet) / 2**20
        print(f"Uploading {size_mb:.1f} MB to {key}")
        try:
            manifest = publish_dataset(storage, local_parquet, args.version)
        except DatasetVersionExistsError:
            print(f"Dataset version {args.version} already exists; versions are never overwritten.")
            return 1

    print(f"Seeded {row_count:,} rows to {key}; split points {manifest['split_points']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
