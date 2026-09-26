import json

import pandas as pd
from fastapi.testclient import TestClient

from services.api.app import create_app
from services.api.routes import feedback as feedback_routes


class FakeAirflow:
    def __init__(self, runs=None):
        self.triggered = []
        self.runs = runs or []

    def trigger_run(self, dag_id, conf):
        self.triggered.append((dag_id, conf))
        return {"run_id": "manual__1", "dag_id": dag_id, "state": "queued"}

    def list_runs(self, dag_id, limit):
        return self.runs[:limit]

    def get_run(self, dag_id, run_id):
        return {"run_id": run_id, "tasks": [{"task_id": "build_feedback_dataset"}]}


class FakeStorage:
    def __init__(self, existing=()):
        self.existing = set(existing)

    def exists(self, key):
        return key in self.existing


def _client(airflow=None, storage=None):
    app = create_app(airflow=airflow or FakeAirflow(), storage=storage or FakeStorage())
    return TestClient(app)


def test_run_starts_the_dag_with_the_period_filled_in():
    airflow = FakeAirflow()
    response = _client(airflow).post(
        "/api/feedback/run", json={"task_type": "regression", "new_version": "v1-fb1"}
    )
    assert response.status_code == 200
    dag_id, conf = airflow.triggered[0]
    assert dag_id == "feedback_data_pipeline"
    assert conf["new_version"] == "v1-fb1"
    assert conf["source_version"] == ""
    assert conf["period_start"] < conf["period_end"]


def test_a_taken_name_is_409_and_nothing_starts():
    airflow = FakeAirflow()
    storage = FakeStorage(existing={"raw/v1/data.parquet"})
    response = _client(airflow, storage).post(
        "/api/feedback/run", json={"task_type": "regression", "new_version": "v1"}
    )
    assert response.status_code == 409
    assert airflow.triggered == []


def test_an_invalid_name_is_422():
    response = _client().post(
        "/api/feedback/run", json={"task_type": "regression", "new_version": "../x"}
    )
    assert response.status_code == 422


def test_a_backwards_period_is_422():
    response = _client().post("/api/feedback/run", json={
        "task_type": "regression", "new_version": "v2",
        "period_start": "2026-09-20T00:00:00+00:00", "period_end": "2026-09-10T00:00:00+00:00",
    })
    assert response.status_code == 422


def test_preview_counts_houses_with_ground_truth(monkeypatch):
    matched = pd.DataFrame({"raw_input": [json.dumps({"property_id": p}) for p in
                                          ["a", "b", "a"]]})
    monkeypatch.setattr(feedback_routes, "matched_predictions", lambda *args: matched)
    body = _client().get("/api/feedback/preview?task_type=regression").json()
    assert body["matched"] == 2
    assert body["minimum"] == 500
    assert body["enough"] is False


def test_status_is_none_before_any_build():
    assert _client().get("/api/feedback/status").json() == {"run": None}


def test_status_reports_the_latest_run_with_tasks():
    airflow = FakeAirflow(runs=[{"run_id": "r1", "state": "success"}])
    body = _client(airflow).get("/api/feedback/status").json()
    assert body["run"]["state"] == "success"
    assert body["run"]["tasks"][0]["task_id"] == "build_feedback_dataset"
