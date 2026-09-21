import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from services.api.clients.registry import RegistryNotFoundError


class FakeRegistry:
    def __init__(self, models=None, promote_error=None):
        self.models = models if models is not None else []
        self.promote_error = promote_error
        self.promoted = []

    def list_models(self):
        return self.models

    def promote(self, name, version):
        if self.promote_error:
            raise self.promote_error
        self.promoted.append((name, version))
        return {"name": name, "version": version, "alias": "champion"}


def _client(registry):
    return TestClient(create_app(registry=registry))


REGRESSION = {
    "name": "house_price_regressor",
    "task_type": "regression",
    "versions": [
        {"version": "3", "metrics": {"rmse": 41203.7, "mae": 28104.2, "r2": 0.947},
         "is_champion": True, "created_at": "2026-09-19T10:00:00+00:00"},
    ],
}

CLASSIFICATION = {
    "name": "house_needs_renovation_classifier",
    "task_type": "classification",
    "versions": [
        {"version": "1", "metrics": {"auc": 0.71, "f1": 0.66, "accuracy": 0.68},
         "is_champion": True, "created_at": "2026-09-19T11:00:00+00:00"},
    ],
}


def test_models_returns_both_registered_models():
    body = _client(FakeRegistry([REGRESSION, CLASSIFICATION])).get("/api/models").json()
    assert [m["name"] for m in body["models"]] == [
        "house_price_regressor",
        "house_needs_renovation_classifier",
    ]


def test_metric_keys_differ_between_task_types():
    # Section 8.1 names hardcoding accuracy/f1 as a defect of the old frontend.
    # The API must report whichever keys the model actually has.
    body = _client(FakeRegistry([REGRESSION, CLASSIFICATION])).get("/api/models").json()
    by_name = {m["name"]: m for m in body["models"]}

    assert set(by_name["house_price_regressor"]["versions"][0]["metrics"]) == {
        "rmse", "mae", "r2",
    }
    assert set(by_name["house_needs_renovation_classifier"]["versions"][0]["metrics"]) == {
        "auc", "f1", "accuracy",
    }


def test_champion_is_flagged():
    body = _client(FakeRegistry([REGRESSION])).get("/api/models").json()
    assert body["models"][0]["versions"][0]["is_champion"] is True


def test_no_registered_models_is_an_empty_list_not_an_error():
    response = _client(FakeRegistry([])).get("/api/models")
    assert response.status_code == 200
    assert response.json()["models"] == []


def test_promote_moves_the_champion_alias():
    registry = FakeRegistry([REGRESSION])
    response = _client(registry).post("/api/models/house_price_regressor/4/promote")

    assert response.status_code == 200
    assert response.json()["alias"] == "champion"
    assert registry.promoted == [("house_price_regressor", "4")]


def test_promote_a_version_that_does_not_exist_is_404():
    registry = FakeRegistry([], promote_error=RegistryNotFoundError("no such version"))
    response = _client(registry).post("/api/models/house_price_regressor/99/promote")
    assert response.status_code == 404


def test_promote_failing_for_another_reason_is_not_a_404():
    # MLflow being down must not read as "that version does not exist".
    registry = FakeRegistry([], promote_error=RuntimeError("mlflow down"))
    client = TestClient(create_app(registry=registry), raise_server_exceptions=False)

    response = client.post("/api/models/house_price_regressor/4/promote")

    assert response.status_code == 500


@pytest.mark.parametrize("version", ["abc", "1.5", "-1", "1a", "%20", "3%0A", "%E0%A5%A7"])
def test_promote_a_version_that_is_not_a_whole_number_is_422_and_never_reaches_the_registry(
    version,
):
    # MLflow answers a non-numeric version with INVALID_PARAMETER_VALUE, which
    # used to escape as a 500. "%20" is a blank version, "%0A" a trailing
    # newline that a lax `$` would let through, and "%E0%A5%A7" the Devanagari
    # digit one, which a `\d` pattern would accept.
    registry = FakeRegistry([REGRESSION])

    response = _client(registry).post(f"/api/models/house_price_regressor/{version}/promote")

    assert response.status_code == 422
    assert registry.promoted == []


def test_promote_passes_a_numeric_version_through_exactly_as_written():
    registry = FakeRegistry([REGRESSION])

    response = _client(registry).post("/api/models/house_price_regressor/3/promote")

    assert response.status_code == 200
    assert registry.promoted == [("house_price_regressor", "3")]
