from datetime import date

import pandas as pd
import pytest
from moto import mock_aws

from ml_common import storage

BUCKET = "test-bucket"


@pytest.fixture
def store():
    with mock_aws():
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield storage.Storage(
            endpoint_url=None,
            access_key="test",
            secret_key="test",
            bucket=BUCKET,
        )


class TestKeyHelpers:
    def test_raw_key(self):
        assert storage.raw_key("v1") == "raw/v1/data.parquet"

    def test_processed_key(self):
        result = storage.processed_key("abc123", "regression", "train")
        assert result == "processed/abc123/regression/train.parquet"
        result = storage.processed_key("abc123", "classification", "test")
        assert result == "processed/abc123/classification/test.parquet"

    def test_processed_key_separates_task_types(self):
        """The fingerprint hashes only the raw data, so two task types share it.

        Their processed files differ (different target, different rows dropped),
        so they must not share a path: one would silently reuse the other's cache.
        """
        regression = storage.processed_key("abc123", "regression", "train")
        classification = storage.processed_key("abc123", "classification", "train")
        assert regression != classification

    def test_processed_prefix_covers_both_splits_of_one_task_type(self):
        prefix = storage.processed_prefix("abc123", "classification")
        assert storage.processed_key("abc123", "classification", "train").startswith(prefix)
        assert storage.processed_key("abc123", "classification", "test").startswith(prefix)
        assert not storage.processed_key("abc123", "regression", "test").startswith(prefix)

    def test_processed_key_invalid_split_raises(self):
        with pytest.raises(ValueError, match="split"):
            storage.processed_key("abc123", "regression", "validation")

    def test_processed_key_invalid_task_type_raises(self):
        with pytest.raises(ValueError, match="task_type"):
            storage.processed_key("abc123", "clustering", "train")

    def test_baseline_key(self):
        result = storage.baseline_key("house_price_regressor", 3)
        assert result == "monitoring-baseline/house_price_regressor/3/profile.json"

    def test_inference_log_key_partitions_by_day(self):
        result = storage.inference_log_key("house_price_regressor", date(2026, 9, 17), "0001")
        assert result == "inference-log/house_price_regressor/dt=2026-09-17/part-0001.parquet"

    def test_ground_truth_key_partitions_by_day(self):
        result = storage.ground_truth_key("house_price_regressor", date(2026, 9, 17), "0001")
        assert result == "ground-truth/house_price_regressor/dt=2026-09-17/part-0001.parquet"

    def test_report_key(self):
        result = storage.report_key("house_price_regressor", "run-42", "html")
        assert result == "reports/house_price_regressor/run-42/evidently.html"

    def test_no_key_starts_with_a_slash(self):
        keys = [
            storage.raw_key("v1"),
            storage.processed_key("a", "regression", "train"),
            storage.baseline_key("m", 1),
            storage.inference_log_key("m", date(2026, 1, 1), "0001"),
            storage.ground_truth_key("m", date(2026, 1, 1), "0001"),
            storage.report_key("m", "r", "json"),
        ]
        for key in keys:
            assert not key.startswith("/"), f"{key} starts with a slash"


class TestStorage:
    def test_write_and_read_parquet_preserves_data(self, store):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        store.write_parquet(df, "some/folder/file.parquet")
        result = store.read_parquet("some/folder/file.parquet")
        pd.testing.assert_frame_equal(df, result)

    def test_write_and_read_json(self, store):
        data = {"name": "test", "count": 42, "items": [1, 2, 3]}
        store.write_json(data, "some/folder/file.json")
        assert store.read_json("some/folder/file.json") == data

    def test_exists_is_correct_for_present_and_absent_keys(self, store):
        store.write_json({"a": 1}, "present/file.json")
        assert store.exists("present/file.json") is True
        assert store.exists("absent/file.json") is False

    def test_list_keys_by_prefix(self, store):
        store.write_json({}, "prefix-a/one.json")
        store.write_json({}, "prefix-a/two.json")
        store.write_json({}, "prefix-b/three.json")
        result = store.list_keys("prefix-a/")
        assert sorted(result) == ["prefix-a/one.json", "prefix-a/two.json"]

    def test_list_keys_missing_prefix_returns_empty_list(self, store):
        assert store.list_keys("does-not-exist/") == []

    def test_reading_a_missing_key_raises(self, store):
        with pytest.raises(FileNotFoundError, match="missing/file.parquet"):
            store.read_parquet("missing/file.parquet")

    def test_overwriting_an_existing_key(self, store):
        store.write_json({"version": 1}, "file.json")
        store.write_json({"version": 2}, "file.json")
        assert store.read_json("file.json") == {"version": 2}


def test_extracted_key():
    assert storage.extracted_key("abc123") == "extracted/abc123/data.parquet"


def test_validation_report_key():
    assert storage.validation_report_key("abc123") == "reports/validation/abc123.json"


def test_object_etag_changes_when_content_changes(store):
    first = pd.DataFrame({"a": [1, 2, 3]})
    second = pd.DataFrame({"a": [9, 9, 9]})

    store.write_parquet(first, "raw/v1/data.parquet")
    etag_before = store.object_etag("raw/v1/data.parquet")

    store.write_parquet(second, "raw/v1/data.parquet")
    etag_after = store.object_etag("raw/v1/data.parquet")

    assert etag_before != etag_after
    assert '"' not in etag_before


def test_object_etag_missing_key_raises(store):
    with pytest.raises(FileNotFoundError):
        store.object_etag("raw/nope/data.parquet")


def test_upload_file_puts_the_bytes_on_storage(store, tmp_path):
    local = tmp_path / "data.parquet"
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(local, index=False)

    store.upload_file(str(local), "raw/v1/data.parquet")

    assert store.exists("raw/v1/data.parquet")
    restored = store.read_parquet("raw/v1/data.parquet")
    assert list(restored["a"]) == [1, 2, 3]


def test_upload_file_missing_local_path_raises(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        store.upload_file(str(tmp_path / "nope.parquet"), "raw/v1/data.parquet")
