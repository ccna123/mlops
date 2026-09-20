from fastapi.testclient import TestClient

from services.api.app import create_app


class FakeAirflow:
    """Stands in for AirflowClient, recording what the routes asked for."""

    def __init__(self, runs=None, run=None):
        self.triggered = []
        self.runs = runs if runs is not None else []
        self.run = run

    def trigger_run(self, dag_id, conf):
        self.triggered.append((dag_id, conf))
        return {"run_id": "manual__2026", "dag_id": dag_id, "state": "queued"}

    def list_runs(self, dag_id, limit):
        return self.runs[:limit]

    def get_run(self, dag_id, run_id):
        return self.run


def _client(airflow):
    return TestClient(create_app(airflow=airflow))


def test_run_triggers_the_dag_and_returns_the_run_id():
    airflow = FakeAirflow()
    response = _client(airflow).post(
        "/api/pipeline/run",
        json={"task_type": "regression", "force_reprocess": False, "sample_rows": 1000},
    )

    assert response.status_code == 200
    assert response.json()["run_id"] == "manual__2026"
    dag_id, conf = airflow.triggered[0]
    assert dag_id == "ml_pipeline"
    assert conf["task_type"] == "regression"
    assert conf["sample_rows"] == 1000


def test_run_defaults_sample_rows_to_none_meaning_every_row():
    airflow = FakeAirflow()
    _client(airflow).post("/api/pipeline/run", json={"task_type": "regression"})

    _, conf = airflow.triggered[0]
    assert conf["sample_rows"] is None


def test_run_rejects_an_unknown_task_type():
    response = _client(FakeAirflow()).post("/api/pipeline/run", json={"task_type": "nonsense"})
    assert response.status_code == 422


def test_run_rejects_a_zero_or_negative_sample_rows():
    client = _client(FakeAirflow())
    for bad in (0, -1):
        response = client.post(
            "/api/pipeline/run", json={"task_type": "regression", "sample_rows": bad}
        )
        assert response.status_code == 422, bad


def test_runs_lists_recent_runs():
    airflow = FakeAirflow(
        runs=[{"run_id": "r1", "state": "success", "task_type": "regression",
               "started_at": "t", "ended_at": "t"}]
    )
    body = _client(airflow).get("/api/pipeline/runs").json()
    assert body["runs"][0]["run_id"] == "r1"


def test_runs_honours_the_limit_query():
    airflow = FakeAirflow(runs=[{"run_id": f"r{i}"} for i in range(10)])
    body = _client(airflow).get("/api/pipeline/runs?limit=3").json()
    assert len(body["runs"]) == 3


def test_run_detail_returns_task_states():
    airflow = FakeAirflow(
        run={"run_id": "r1", "state": "running",
             "tasks": [{"task_id": "extract", "state": "success",
                        "try_number": 1, "duration": 12.5}]}
    )
    body = _client(airflow).get("/api/pipeline/runs/r1").json()
    assert body["tasks"][0]["task_id"] == "extract"
