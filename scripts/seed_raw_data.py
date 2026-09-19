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
