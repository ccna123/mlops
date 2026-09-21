from datetime import date

import pandas as pd
import pytest
from botocore.exceptions import ClientError
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


def test_drift_summary_key_sits_beside_the_evidently_report():
    from ml_common.storage import drift_summary_key, report_key

    summary = drift_summary_key("house_price_regressor", "abc123")
    assert summary == "reports/house_price_regressor/abc123/summary.json"
    # Same run prefix as the full report, so one listing finds both.
    assert summary.rsplit("/", 1)[0] == report_key(
        "house_price_regressor", "abc123", "html"
    ).rsplit("/", 1)[0]


def test_drift_latest_key_is_one_object_per_model():
    from ml_common.storage import drift_latest_key

    assert drift_latest_key("house_price_regressor") == "reports/house_price_regressor/latest.json"


def test_drift_prefix_holds_every_drift_object_of_one_model():
    from ml_common.storage import (
        drift_latest_key,
        drift_prefix,
        drift_summary_key,
        report_key,
    )

    prefix = drift_prefix("house_price_regressor")

    assert prefix == "reports/house_price_regressor/"
    assert drift_summary_key("house_price_regressor", "abc123").startswith(prefix)
    assert drift_latest_key("house_price_regressor").startswith(prefix)
    assert report_key("house_price_regressor", "abc123", "html").startswith(prefix)


def test_drift_prefix_does_not_match_a_model_whose_name_merely_starts_the_same():
    from ml_common.storage import drift_prefix, drift_summary_key

    other = drift_summary_key("house_price_regressor_v2", "abc123")
    assert not other.startswith(drift_prefix("house_price_regressor"))


def test_is_drift_summary_key_accepts_what_drift_summary_key_builds():
    from ml_common.storage import drift_summary_key, is_drift_summary_key

    assert is_drift_summary_key(drift_summary_key("house_price_regressor", "20260920T0800"))


def test_is_drift_summary_key_rejects_the_other_objects_under_the_same_prefix():
    from ml_common.storage import drift_latest_key, is_drift_summary_key, report_key

    assert not is_drift_summary_key(drift_latest_key("house_price_regressor"))
    assert not is_drift_summary_key(report_key("house_price_regressor", "abc123", "html"))
    assert not is_drift_summary_key(report_key("house_price_regressor", "abc123", "json"))


def test_is_drift_summary_key_rejects_keys_from_outside_the_reports_tree():
    from ml_common.storage import is_drift_summary_key, validation_report_key

    assert not is_drift_summary_key(validation_report_key("abc123"))
    assert not is_drift_summary_key("inference-log/m/dt=2026-09-20/summary.json")


class TestReadParquetHead:
    def test_returns_exactly_rows_and_the_true_total_when_the_file_is_bigger(self, store):
        frame = pd.DataFrame({"a": [str(i) for i in range(25)]})
        store.write_parquet(frame, "raw/v1/data.parquet")

        head, total = store.read_parquet_head("raw/v1/data.parquet", 10)

        assert total == 25
        assert list(head["a"]) == [str(i) for i in range(10)]

    def test_returns_every_row_when_the_file_is_smaller_than_rows(self, store):
        frame = pd.DataFrame({"a": ["x", "y", "z"]})
        store.write_parquet(frame, "raw/v1/data.parquet")

        head, total = store.read_parquet_head("raw/v1/data.parquet", 100)

        assert total == 3
        assert list(head["a"]) == ["x", "y", "z"]

    def test_rows_larger_than_one_row_group_still_returns_rows(self, store, tmp_path):
        local = tmp_path / "grouped.parquet"
        frame = pd.DataFrame({"a": [str(i) for i in range(50)]})
        frame.to_parquet(local, index=False, row_group_size=7)
        store.upload_file(str(local), "raw/v1/data.parquet")

        head, total = store.read_parquet_head("raw/v1/data.parquet", 20)

        assert total == 50
        assert list(head["a"]) == [str(i) for i in range(20)]

    def test_an_empty_file_gives_an_empty_frame_with_its_columns_and_total_zero(self, store):
        empty = pd.DataFrame(
            {"a": pd.Series([], dtype="object"), "b": pd.Series([], dtype="object")}
        )
        store.write_parquet(empty, "raw/v1/data.parquet")

        head, total = store.read_parquet_head("raw/v1/data.parquet", 10)

        assert total == 0
        assert len(head) == 0
        assert list(head.columns) == ["a", "b"]

    def test_a_missing_key_raises_file_not_found(self, store):
        with pytest.raises(FileNotFoundError, match="missing/file.parquet"):
            store.read_parquet_head("missing/file.parquet", 10)

    def test_string_columns_stay_strings(self, store):
        frame = pd.DataFrame({"zip": ["02134", "00501"], "price": ["$450,000", None]})
        store.write_parquet(frame, "raw/v1/data.parquet")

        head, _ = store.read_parquet_head("raw/v1/data.parquet", 10)

        assert list(head["zip"]) == ["02134", "00501"]
        assert head["price"].iloc[0] == "$450,000"
        assert pd.isna(head["price"].iloc[1])

    def test_rows_below_one_is_rejected_before_any_download(self, store):
        with pytest.raises(ValueError, match="rows must be at least 1"):
            store.read_parquet_head("missing/file.parquet", 0)


class TestCheckReachable:
    def test_succeeds_when_the_bucket_exists(self, store):
        assert store.check_reachable() is None

    def test_raises_when_the_bucket_does_not_exist(self):
        with mock_aws():
            missing = storage.Storage(
                endpoint_url=None,
                access_key="test",
                secret_key="test",
                bucket="no-such-bucket",
            )

            with pytest.raises(ClientError):
                missing.check_reachable()

    def test_touches_no_object_and_lists_nothing(self, store):
        # /health polls this, so it must stay one bucket-level request no matter
        # how many objects the bucket holds.
        store.write_json({"a": 1}, "reports/x.json")
        calls = []
        real_client = store._client

        class Recorder:
            def __getattr__(self, name):
                calls.append(name)
                return getattr(real_client, name)

        store._client = Recorder()

        store.check_reachable()

        assert calls == ["head_bucket"]
