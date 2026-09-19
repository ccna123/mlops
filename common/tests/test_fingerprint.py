"""Tests for the cache key that ties processed data back to its raw input."""

from ml_common.fingerprint import compute_fingerprint


def test_same_input_gives_same_fingerprint():
    first = compute_fingerprint("v1", "abc", 200000)
    second = compute_fingerprint("v1", "abc", 200000)
    assert first == second


def test_fingerprint_is_short_lowercase_hex():
    result = compute_fingerprint("v1", "abc", None)
    assert len(result) == 16
    assert all(char in "0123456789abcdef" for char in result)


def test_different_sample_rows_gives_different_fingerprint():
    sampled = compute_fingerprint("v1", "abc", 200000)
    full = compute_fingerprint("v1", "abc", None)
    assert sampled != full


def test_different_etag_gives_different_fingerprint():
    before = compute_fingerprint("v1", "abc", 200000)
    after = compute_fingerprint("v1", "xyz", 200000)
    assert before != after


def test_different_dataset_version_gives_different_fingerprint():
    first = compute_fingerprint("v1", "abc", 200000)
    second = compute_fingerprint("v2", "abc", 200000)
    assert first != second


def test_sample_rows_zero_is_not_the_same_as_no_limit():
    """0 rows and 'no limit' are different requests; they must not share a cache."""
    assert compute_fingerprint("v1", "abc", 0) != compute_fingerprint("v1", "abc", None)
