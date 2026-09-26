"""The cache keys that tie stored data back to the raw input it came from.

Two keys, for two caches (02 3.2):

- The working copy ID names the full raw dataset as extracted to parquet. It
  depends only on the dataset version and the raw object's ETag, so every run
  on the same data reuses the same working copy whatever row limit it asks for.
- The data ID names the prepared train and test sets. It adds the row limit and
  the random seed used to sample the train set, because either one changes
  which rows the model learns from. Leaving the row limit out would let a
  200k-row run silently reuse the train set built from every row.

The data ID is what the pipeline calls `fingerprint` in XCom and in MLflow
params, so models registered before the split was made temporal still trace
back to their train set under the same name.
"""

from __future__ import annotations

import hashlib

_LENGTH = 16


def _digest(payload: str) -> str:
    """Hashes a payload to the short hex form every cache key uses.

    Args:
        payload: the text to hash.

    Returns:
        16 lowercase hex characters.

    Example:
        _digest("v1|abc")  # -> "e3b0c44298fc1c14" (some 16-char value)
    """
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_LENGTH]


def compute_working_copy_id(dataset_version: str, etag: str) -> str:
    """Builds the cache key of the full extracted dataset.

    Args:
        dataset_version: the raw dataset version, e.g. "v1".
        etag: ETag of the raw object; it already changes whenever the file does,
            so there is no need to read and hash 2 million rows.

    Returns:
        16 lowercase hex characters.

    Example:
        etag = storage.object_etag(raw_key("v1"))
        compute_working_copy_id("v1", etag)  # -> "9d41c07a2be35f10"
    """
    return _digest(f"{dataset_version}|{etag}")


def compute_data_id(working_copy_id: str, sample_rows: int | None, seed: int) -> str:
    """Builds the cache key of the prepared train and test sets.

    Args:
        working_copy_id: what `compute_working_copy_id` returned.
        sample_rows: how many train rows this run samples, or None for all.
        seed: the random seed the sample is drawn with.

    Returns:
        16 lowercase hex characters.

    Example:
        compute_data_id("9d41c07a2be35f10", 200_000, 42)  # -> "3f0a9c1d5e2b7a48"
        compute_data_id("9d41c07a2be35f10", None, 42)     # -> a DIFFERENT value

        # That difference is the point: a 200k-row dev run must never reuse
        # the train set sampled for a run on every row.
    """
    limit = "all" if sample_rows is None else str(sample_rows)
    return _digest(f"{working_copy_id}|{limit}|{seed}")
