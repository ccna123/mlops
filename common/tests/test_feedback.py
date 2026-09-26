import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from moto import mock_aws

from ml_common import datasets, feedback, preparation, splits, storage

BUCKET = "feedback-test"
MODEL = "house_price_regressor"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
def store():
    with mock_aws():
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield storage.Storage(None, "k", "s", BUCKET)


def _source(n=1000) -> pd.DataFrame:
    days = pd.date_range("2020-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "property_id": [f"p{i}" for i in range(n)],
        "listing_date": list(days),
        "city": ["boston"] * n,
        "condition": ["good"] * n,
        "sale_price": ["100000"] * n,
    })


def _publish_source(store, tmp_path, version="v1"):
    path = tmp_path / "source.parquet"
    _source().to_parquet(path, index=False)
    return datasets.publish_dataset(store, str(path), version)


def _serve(store, ids, actual, start=NOW - timedelta(hours=2)):
    """Writes predictions one second apart, and their ground truth."""
    stamps = [start + timedelta(seconds=i) for i in range(len(ids))]
    log = pd.DataFrame({
        "request_id": [f"r{i}" for i in range(len(ids))],
        "timestamp": [s.isoformat() for s in stamps],
        "raw_input": [json.dumps({"property_id": pid, "listing_date": "2020-01-05",
                                  "city": "MIAMI", "bedrooms": 3}) for pid in ids],
        "prediction": [1.0] * len(ids),
        "probability": [None] * len(ids),
        "model_name": [MODEL] * len(ids),
        "model_version": ["1"] * len(ids),
    })
    store.write_parquet(log, storage.inference_log_key(MODEL, start.date(), "a"))
    truth = pd.DataFrame({"request_id": log["request_id"], "predicted_on": start.date().isoformat(),
                          "actual": actual, "model_name": MODEL})
    store.write_parquet(truth, storage.ground_truth_key(MODEL, start.date(), "b"))


def _build(store, new_version="v1-fb1", task_type="regression"):
    return feedback.build_feedback_dataset(
        store, task_type=task_type, model_name=MODEL, source_version="v1",
        start=NOW - timedelta(days=1), end=NOW, new_version=new_version,
    )


def test_feedback_version_replaces_same_houses_and_records_lineage(store, tmp_path):
    _publish_source(store, tmp_path)
    ids = [f"p{i}" for i in range(0, 100)] + [f"new{i}" for i in range(500)]
    _serve(store, ids, actual=np.full(600, 250_000.0))

    manifest = _build(store)

    data = store.read_parquet(storage.raw_key("v1-fb1"))
    assert len(data) == 1000 - 100 + 600
    assert manifest["lineage"]["feedback_records"] == 600
    assert manifest["lineage"]["replaced_records"] == 100
    assert manifest["lineage"]["source_version"] == "v1"
    feedback_rows = data[data[splits.SOURCE_COLUMN] == splits.SOURCE_FEEDBACK]
    assert set(feedback_rows["sale_price"]) == {"250000.0"}
    assert (data["property_id"] == "p0").sum() == 1  # the old record is gone


def test_split_points_put_the_latest_feedback_in_test_and_keep_simulation(store, tmp_path):
    source_manifest = _publish_source(store, tmp_path)
    _serve(store, [f"new{i}" for i in range(600)], actual=np.full(600, 1.0))

    manifest = _build(store)
    data = store.read_parquet(storage.raw_key("v1-fb1"))
    assigned = splits.assign_split(data, manifest["split_points"])

    is_feedback = data[splits.SOURCE_COLUMN] == splits.SOURCE_FEEDBACK
    assert (assigned[is_feedback] == "test").sum() == 120  # latest 20% of 600
    assert (assigned[~is_feedback] == "test").sum() == 0
    source_sim = splits.assign_split(_source(), source_manifest["split_points"]) == "simulation"
    assert (assigned[~is_feedback] == "simulation").sum() == source_sim.sum()
    latest_train = data.loc[is_feedback & (assigned == "train"), "predicted_at"].max()
    earliest_test = data.loc[is_feedback & (assigned == "test"), "predicted_at"].min()
    assert latest_train < earliest_test


def test_too_little_feedback_is_refused_and_nothing_written(store, tmp_path):
    _publish_source(store, tmp_path)
    _serve(store, [f"new{i}" for i in range(499)], actual=np.full(499, 1.0))
    with pytest.raises(feedback.NotEnoughFeedbackError, match="500"):
        _build(store)
    assert not datasets.dataset_exists(store, "v1-fb1")


def test_an_existing_name_is_refused(store, tmp_path):
    _publish_source(store, tmp_path)
    with pytest.raises(datasets.DatasetVersionExistsError):
        _build(store, new_version="v1")


def test_a_house_predicted_twice_keeps_its_latest_outcome(store, tmp_path):
    matched = pd.DataFrame({
        "raw_input": [json.dumps({"property_id": "p1"})] * 2,
        "actual": [100.0, 200.0],
        "timestamp": ["2026-09-26T10:00:00+00:00", "2026-09-26T11:00:00+00:00"],
    })
    records = feedback.build_feedback_records(matched, "regression")
    assert list(records["sale_price"]) == ["200.0"]


def test_classification_feedback_is_read_as_the_label_by_prepare(store, tmp_path):
    _publish_source(store, tmp_path)
    ids = [f"new{i}" for i in range(600)]
    _serve(store, ids, actual=[True, False] * 300)
    manifest = _build(store, task_type="classification")
    data = store.read_parquet(storage.raw_key("v1-fb1"))

    light = data[preparation.light_columns("classification", data.columns.tolist())]
    plan = preparation.plan_rows(light, "classification", manifest["split_points"], None, 42)

    # source rows all say condition "good" (label False); the feedback labels
    # are what put True labels into the prepared sets.
    kept = np.concatenate([plan.train_positions, plan.test_positions])
    assert (data.iloc[kept]["needs_renovation"] == "True").sum() == 300
    assert plan.counts["dropped_missing_target"] == 0
