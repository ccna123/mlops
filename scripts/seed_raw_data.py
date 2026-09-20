"""Seeds the raw dataset into MinIO. Run once, by hand, from the repo root.

The pipeline's `extract` stage reads only from object storage, the way a real
system does: raw data is delivered by something upstream, not produced by the
pipeline itself. This script is that upstream delivery, done by hand.
"""

from __future__ import annotations

import argparse
import os
import tempfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ml_common.storage import Storage, raw_key

CHUNK_ROWS = 200_000
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


def csv_to_parquet(source: str, destination: str, limit: int | None) -> int:
    """Streams the CSV into a parquet file, a chunk at a time.

    Every column is read as text on purpose: this is the RAW copy, and parsing
    belongs to the Pipeline. Letting pandas infer types here would quietly fix
    some of the dirt the pipeline exists to handle.

    Args:
        source: path to the CSV. Read 200k rows at a time, so a 373 MB file
            never has to fit in memory whole.
        destination: path of the parquet file to write.
        limit: stop after this many rows, or None for all of them.

    Returns:
        How many rows were written. The parquet file is closed either way, so
        an interrupted run leaves a readable partial file rather than a corrupt
        one.

    Example:
        csv_to_parquet("house_pricing_dirty.csv", "/tmp/data.parquet", None)
        # -> 2000000, printing progress every 200k rows

        # Every column lands as a STRING. "$450,000" stays "$450,000" and
        # "09/20/2026" stays text — letting pandas infer types here would
        # quietly repair some of the dirt the pipeline exists to handle.
    """
    written = 0
    writer = None
    try:
        reader = pd.read_csv(source, chunksize=CHUNK_ROWS, dtype=str, keep_default_na=False)
        for chunk in reader:
            if limit is not None and written + len(chunk) > limit:
                chunk = chunk.head(limit - written)
            if chunk.empty:
                break
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(destination, table.schema, compression="snappy")
            writer.write_table(table)
            written += len(chunk)
            print(f"  ... {written:,} rows")
            if limit is not None and written >= limit:
                break
    finally:
        if writer is not None:
            writer.close()
    return written


def main() -> int:
    r"""Converts the CSV to parquet and uploads it as the raw dataset.

    Args:
        None. Takes its settings from the command line, and the MinIO
        variables `Storage.from_env` needs from the environment.

    Returns:
        0. The parquet file is built in a temporary directory that is removed
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

    with tempfile.TemporaryDirectory() as workdir:
        local_parquet = os.path.join(workdir, "data.parquet")
        print(f"Converting {args.source} -> parquet")
        row_count = csv_to_parquet(args.source, local_parquet, args.limit)
        size_mb = os.path.getsize(local_parquet) / 2**20
        print(f"Uploading {size_mb:.1f} MB to {key}")
        storage.upload_file(local_parquet, key)

    print(f"Seeded {row_count:,} rows to {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
