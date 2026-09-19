"""Extract stage: pick the rows this run will use and park them under a fingerprint.

Reads the raw dataset from object storage, applies SAMPLE_ROWS, and writes the
result to a fingerprint-addressed prefix. The fingerprint computed here is what
every later stage uses to find its input.
"""

from __future__ import annotations

import json
import os
import sys

from ml_common.fingerprint import compute_fingerprint
from ml_common.storage import Storage, extracted_key, raw_key


def read_sample_rows() -> int | None:
    """Reads SAMPLE_ROWS, treating empty or unset as 'use every row'."""
    raw_value = os.environ.get("SAMPLE_ROWS", "").strip()
    if not raw_value:
        return None
    return int(raw_value)


def main() -> int:
    dataset_version = os.environ.get("DATASET_VERSION", "v1")
    sample_rows = read_sample_rows()
    storage = Storage.from_env()

    source = raw_key(dataset_version)
    etag = storage.object_etag(source)
    fingerprint = compute_fingerprint(dataset_version, etag, sample_rows)
    destination = extracted_key(fingerprint)

    print(f"raw={source} etag={etag} sample_rows={sample_rows}", file=sys.stderr)

    if storage.exists(destination):
        row_count = len(storage.read_parquet(destination))
        print(f"reusing existing {destination}", file=sys.stderr)
    else:
        df = storage.read_parquet(source)
        if sample_rows is not None:
            df = df.head(sample_rows)
        storage.write_parquet(df, destination)
        row_count = len(df)
        print(f"wrote {row_count} rows to {destination}", file=sys.stderr)

    print(json.dumps({"fingerprint": fingerprint, "row_count": int(row_count)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
