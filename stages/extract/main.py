"""Extract stage: pick the rows this run will use and park them under a fingerprint.

Reads the raw dataset from object storage, applies SAMPLE_ROWS, and writes the
result to a fingerprint-addressed prefix. The fingerprint computed here is what
every later stage uses to find its input.
"""

from __future__ import annotations

import os
import sys

from ml_common.fingerprint import compute_fingerprint
from ml_common.stageio import emit_result
from ml_common.storage import Storage, extracted_key, raw_key


def read_sample_rows() -> int | None:
    """Reads the SAMPLE_ROWS limit for this run.

    Args:
        None. Reads the SAMPLE_ROWS environment variable.

    Returns:
        The row limit, or None when the variable is unset or empty — both mean
        "use every row". The value is part of the fingerprint, so a sampled run
        can never reuse the full run's processed data.

    Raises:
        ValueError: when the variable holds something that is not a number.
            Falling back to "every row" would start a 2-million-row run on a
            machine that asked for 200k.

    Example:
        # SAMPLE_ROWS=200000  -> 200000   (the dev setting, from .env)
        # SAMPLE_ROWS=""      -> None     (a real run)
        # SAMPLE_ROWS unset   -> None
        # SAMPLE_ROWS="lots"  -> ValueError
    """
    raw_value = os.environ.get("SAMPLE_ROWS", "").strip()
    if not raw_value:
        return None
    return int(raw_value)


def main() -> int:
    """Samples the raw dataset and parks it under a fingerprint.

    Args:
        None. Reads DATASET_VERSION (default "v1"), SAMPLE_ROWS, and the MinIO
        variables `Storage.from_env` needs.

    Returns:
        0. Emits `fingerprint` and `row_count` as the stage result, which every
        later stage uses to find its input. When the fingerprint already has
        extracted data, that data is reused rather than rewritten.

    Raises:
        FileNotFoundError: when the raw object for that dataset version is not
            in storage. Nothing downstream can run, so the stage fails loudly
            rather than emitting a fingerprint for data that does not exist.
    """
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

    emit_result({"fingerprint": fingerprint, "row_count": int(row_count)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
