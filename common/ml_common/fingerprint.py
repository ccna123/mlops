"""The cache key that ties processed data back to the raw input it came from.

`prepare_dataset_for_train` skips its work when data for a fingerprint already
exists, so anything that changes which rows the pipeline sees MUST be part of
the fingerprint. Leaving SAMPLE_ROWS out would let a 200k-row run silently
reuse the split built from 2 million rows.
"""

from __future__ import annotations

import hashlib

_LENGTH = 16


def compute_fingerprint(dataset_version: str, etag: str, sample_rows: int | None) -> str:
    """Builds the cache key for one combination of raw data and row limit.

    Args:
        dataset_version: the raw dataset version, e.g. "v1".
        etag: ETag of the raw object; it already changes whenever the file does,
            so there is no need to read and hash 2 million rows.
        sample_rows: row limit for this run, or None to use every row.

    Returns:
        16 lowercase hex characters.
    """
    limit = "all" if sample_rows is None else str(sample_rows)
    payload = f"{dataset_version}|{etag}|{limit}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_LENGTH]
