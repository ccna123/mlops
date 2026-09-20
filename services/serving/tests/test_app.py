"""Tests for the serving routes, with fake models instead of MLflow and MinIO."""

import json

import pytest
from fastapi.testclient import TestClient

from ml_common.inference_log import InferenceLogBuffer
from services.serving.app import create_app
from services.serving.model_registry import LoadedModel, ModelRegistry


class FakeModel:
    """Returns a fixed answer, and records what it was given."""

    def __init__(self, value=412350.75, proba=0.83):
        self.value = value
        self.proba = proba
        self.seen = None

    def predict(self, frame):
        self.seen = frame
        return [self.value] * len(frame)

    def predict_proba(self, frame):
        return [[1 - self.proba, self.proba]] * len(frame)


def _registry(loaded: dict) -> ModelRegistry:
    registry = ModelRegistry(loader=lambda name: (_ for _ in ()).throw(RuntimeError("unused")))
    registry._loaded = loaded  # noqa: SLF001 - deliberate: this is the seam under test
    return registry


def _client(loaded: dict, buffer=None, flush=None) -> TestClient:
    app = create_app(
        registry=_registry(loaded),
        buffer=buffer or InferenceLogBuffer(),
        flush=flush or (lambda records: None),
        start_flusher=False,
    )
    return TestClient(app)


RAW_RECORD = {
    "city": "  NEW YORK ",
    "list_price": "$450,000",
    "bedrooms": 3,
    "zipcode": "10001",
}


def test_health_reports_degraded_when_nothing_is_loaded():
    response = _client({"regression": None, "classification": None}).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_health_reports_ok_when_one_model_is_loaded():
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", FakeModel()),
        "classification": None,
    }
    body = _client(loaded).get("/health").json()
    assert body["status"] == "ok"
    assert body["models"]["regression"]["version"] == "3"
    assert body["models"]["classification"]["loaded"] is False


def test_health_reports_buffer_counts():
    body = _client({"regression": None, "classification": None}).get("/health").json()
    assert body["inference_log"] == {"buffered": 0, "dropped": 0}


def test_predict_on_a_model_that_is_not_loaded_returns_503():
    """Not ready is not the same as broken; 500 would tell the caller to give up."""
    response = _client({"regression": None, "classification": None}).post(
        "/predict/regression", json=RAW_RECORD
    )
    assert response.status_code == 503


def test_predict_with_an_unknown_model_name_returns_422():
    response = _client({"regression": None, "classification": None}).post(
        "/predict/clustering", json=RAW_RECORD
    )
    assert response.status_code == 422


def test_predict_returns_prediction_and_provenance():
    model = FakeModel()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", model),
        "classification": None,
    }
    body = _client(loaded).post("/predict/regression", json=RAW_RECORD).json()
    assert body["prediction"] == 412350.75
    assert body["model_name"] == "house_price_regressor"
    assert body["model_version"] == "3"
    assert len(body["request_id"]) > 0


def test_the_model_receives_the_record_untouched():
    """Serving must not clean anything: the Pipeline inside the model does that."""
    model = FakeModel()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", model),
        "classification": None,
    }
    _client(loaded).post("/predict/regression", json=RAW_RECORD)
    assert model.seen["list_price"].iloc[0] == "$450,000"
    assert model.seen["city"].iloc[0] == "  NEW YORK "


def test_classification_returns_a_boolean_and_a_probability():
    model = FakeModel(value=True, proba=0.83)
    loaded = {
        "regression": None,
        "classification": LoadedModel("house_needs_renovation_classifier", "1", model),
    }
    body = _client(loaded).post("/predict/classification", json=RAW_RECORD).json()
    assert body["prediction"] is True
    assert body["probability"] == pytest.approx(0.83)


def test_a_record_missing_optional_columns_is_accepted():
    """The Pipeline imputes; rejecting these would be stricter than the model."""
    model = FakeModel()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", model),
        "classification": None,
    }
    response = _client(loaded).post("/predict/regression", json={"city": "austin"})
    assert response.status_code == 200


def test_each_prediction_adds_exactly_one_buffered_record():
    buffer = InferenceLogBuffer()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", FakeModel()),
        "classification": None,
    }
    client = _client(loaded, buffer=buffer)
    client.post("/predict/regression", json=RAW_RECORD)
    client.post("/predict/regression", json=RAW_RECORD)
    assert buffer.stats()["buffered"] == 2


def test_the_buffered_record_carries_everything_plan_4_needs():
    buffer = InferenceLogBuffer()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", FakeModel()),
        "classification": None,
    }
    _client(loaded, buffer=buffer).post("/predict/regression", json=RAW_RECORD)
    record = buffer.take()[0]
    assert set(record) >= {
        "request_id",
        "timestamp",
        "raw_input",
        "prediction",
        "model_name",
        "model_version",
        "day",
    }
    assert json.loads(record["raw_input"])["list_price"] == "$450,000"


def test_a_failing_flush_never_reaches_the_caller():
    """Logging is secondary to serving; a broken MinIO must not break /predict."""

    def broken_flush(records):
        raise RuntimeError("MinIO is down")

    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", FakeModel()),
        "classification": None,
    }
    response = _client(loaded, flush=broken_flush).post("/predict/regression", json=RAW_RECORD)
    assert response.status_code == 200


def test_reload_returns_the_same_models_block_as_health():
    loaded = {"regression": None, "classification": None}
    client = _client(loaded)
    assert client.post("/reload").json()["models"] == client.get("/health").json()["models"]


def test_shutdown_flushes_a_partial_batch():
    """Below 500 records and under 30 seconds, only shutdown can save these."""
    written: list[dict] = []
    registry = ModelRegistry(loader=lambda name: (FakeModel(), "3"))
    app = create_app(
        registry=registry,
        buffer=InferenceLogBuffer(),
        flush=written.extend,
        start_flusher=False,
    )
    with TestClient(app) as client:
        client.post("/predict/regression", json=RAW_RECORD)
        assert written == []
    assert len(written) == 1
