from fastapi.testclient import TestClient

from services.api.app import create_app


def _client(probes: dict) -> TestClient:
    return TestClient(create_app(probes=probes))


def test_health_is_ok_when_every_dependency_answers():
    client = _client({"airflow": lambda: True, "mlflow": lambda: True})
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["services"] == {"airflow": "ok", "mlflow": "ok"}


def test_health_is_degraded_when_one_dependency_is_down():
    client = _client({"airflow": lambda: True, "mlflow": lambda: False})
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["services"]["mlflow"] == "down"


def test_a_probe_that_raises_counts_as_down_not_a_crash():
    def explode():
        raise RuntimeError("connection refused")

    client = _client({"airflow": explode})
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["services"]["airflow"] == "down"


def test_health_always_returns_200_even_when_everything_is_down():
    client = _client({"airflow": lambda: False, "mlflow": lambda: False})
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
