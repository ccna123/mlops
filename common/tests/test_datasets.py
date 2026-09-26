import pandas as pd
import pytest
from moto import mock_aws

from ml_common import datasets, storage

BUCKET = "test-bucket"


@pytest.fixture
def store():
    with mock_aws():
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield storage.Storage(None, "test", "test", BUCKET)


@pytest.fixture
def local_parquet(tmp_path):
    days = [d.strftime("%m/%d/%Y") for d in pd.date_range("2020-01-01", periods=200)]
    frame = pd.DataFrame({"property_id": [f"p{i}" for i in range(200)], "listing_date": days})
    path = tmp_path / "data.parquet"
    frame.to_parquet(path, index=False)
    return str(path)


def test_publish_writes_data_and_manifest(store, local_parquet):
    manifest = datasets.publish_dataset(store, local_parquet, "v2")
    assert store.exists(storage.raw_key("v2"))
    assert datasets.read_manifest(store, "v2") == manifest
    assert manifest["row_count"] == 200


def test_publish_refuses_an_existing_version(store, local_parquet):
    datasets.publish_dataset(store, local_parquet, "v2")
    etag = store.object_etag(storage.raw_key("v2"))
    with pytest.raises(datasets.DatasetVersionExistsError):
        datasets.publish_dataset(store, local_parquet, "v2")
    assert store.object_etag(storage.raw_key("v2")) == etag


def test_raw_data_without_manifest_still_owns_its_name(store, local_parquet):
    store.upload_file(local_parquet, storage.raw_key("v1"))
    with pytest.raises(datasets.DatasetVersionExistsError):
        datasets.publish_dataset(store, local_parquet, "v1")


def test_data_without_listing_dates_is_rejected_and_nothing_is_written(store, tmp_path):
    path = tmp_path / "nodates.parquet"
    pd.DataFrame({"property_id": ["p1"], "city": ["x"]}).to_parquet(path, index=False)
    with pytest.raises(ValueError, match="listing_date"):
        datasets.publish_dataset(store, str(path), "v3")
    assert not datasets.dataset_exists(store, "v3")


def test_ensure_manifest_creates_once_then_reads_back(store, local_parquet):
    store.upload_file(local_parquet, storage.raw_key("v1"))
    first = datasets.ensure_manifest(store, "v1")
    second = datasets.ensure_manifest(store, "v1")
    assert first == second
    assert store.exists(storage.dataset_manifest_key("v1"))


def test_ensure_manifest_without_data_raises(store):
    with pytest.raises(FileNotFoundError):
        datasets.ensure_manifest(store, "missing")
