from fastapi.testclient import TestClient

from services.agent.scenarios import SCENARIOS
from services.api.app import create_app

TRAFFIC_DAG = "traffic_agent"


class FakeAirflow:
    """Stands in for AirflowClient, recording what the route asked it to do."""

    def __init__(self, runs=None, tasks=None):
        self.triggered = []
        self.runs = runs if runs is not None else []
        self.listed = []
        self.fetched = []
        self.tasks = tasks if tasks is not None else []

    def trigger_run(self, dag_id, conf):
        self.triggered.append((dag_id, conf))
        return {"run_id": "manual__2026", "dag_id": dag_id, "state": "queued"}

    def list_runs(self, dag_id, limit):
        self.listed.append((dag_id, limit))
        return self.runs[:limit]

    def get_run(self, dag_id, run_id):
        self.fetched.append((dag_id, run_id))
        return {"run_id": run_id, "state": "running", "tasks": self.tasks}


def _client(airflow=None):
    return TestClient(create_app(airflow=airflow if airflow is not None else FakeAirflow()))


# --- POST /api/simulate -----------------------------------------------------


def test_simulate_triggers_the_traffic_agent_dag_with_the_chosen_scenario():
    airflow = FakeAirflow()

    response = _client(airflow).post(
        "/api/simulate",
        json={"scenario": "market_shift", "task_type": "regression", "count": 300},
    )

    assert response.status_code == 200
    assert response.json()["run_id"] == "manual__2026"
    dag_id, conf = airflow.triggered[0]
    assert dag_id == TRAFFIC_DAG
    assert conf["scenario"] == "market_shift"
    assert conf["task_type"] == "regression"
    assert conf["count"] == 300


def test_simulate_defaults_to_undistorted_traffic():
    # An empty body must not secretly distort anything: "none" is real traffic.
    airflow = FakeAirflow()

    _client(airflow).post("/api/simulate", json={"task_type": "regression"})

    assert airflow.triggered[0][1]["scenario"] == "none"


def test_simulate_rejects_a_scenario_the_agent_does_not_have():
    # Caught here rather than in the container, where a typo would surface
    # minutes later as a failed task.
    airflow = FakeAirflow()

    response = _client(airflow).post(
        "/api/simulate", json={"scenario": "market_crash", "task_type": "regression"}
    )

    assert response.status_code == 422
    assert airflow.triggered == []


def test_simulate_rejects_an_unknown_task_type():
    response = _client().post("/api/simulate", json={"task_type": "clustering"})
    assert response.status_code == 422


def test_simulate_rejects_a_count_of_zero_or_less():
    for count in (0, -1):
        response = _client().post(
            "/api/simulate", json={"task_type": "regression", "count": count}
        )
        assert response.status_code == 422, count


def test_simulate_rejects_a_count_beyond_the_cap():
    # Every request is one real HTTP call to serving; an unbounded count would
    # hold a container open for hours.
    response = _client().post("/api/simulate", json={"task_type": "regression", "count": 100_000})
    assert response.status_code == 422


# --- GET /api/scenarios -----------------------------------------------------


def test_scenarios_come_straight_from_the_agent():
    body = _client().get("/api/scenarios").json()
    assert body["scenarios"] == list(SCENARIOS)


def test_scenarios_offers_every_name_simulate_accepts():
    airflow = FakeAirflow()
    client = _client(airflow)

    for scenario in client.get("/api/scenarios").json()["scenarios"]:
        response = client.post(
            "/api/simulate", json={"scenario": scenario, "task_type": "regression"}
        )
        assert response.status_code == 200, scenario


# --- GET /api/simulate/status -----------------------------------------------


def test_status_reports_the_newest_traffic_run():
    run = {
        "run_id": "manual__2026",
        "state": "running",
        "task_type": "regression",
        "started_at": "2026-09-22T10:00:00+00:00",
        "ended_at": None,
    }
    airflow = FakeAirflow(runs=[run])

    body = _client(airflow).get("/api/simulate/status").json()

    assert body["run"]["run_id"] == "manual__2026"
    assert body["run"]["state"] == "running"
    assert airflow.listed == [(TRAFFIC_DAG, 1)]


def test_status_carries_the_state_of_every_task_in_the_run():
    # The dashboard draws these as a progress strip, so the user never has to
    # open Airflow to find out which half of the chain is running.
    run = {"run_id": "manual__2026", "state": "running", "task_type": None,
           "started_at": None, "ended_at": None}
    tasks = [
        {"task_id": "send_traffic", "state": "success", "try_number": 1, "duration": 29.0},
        {"task_id": "compute_drift", "state": "running", "try_number": 1, "duration": None},
    ]
    airflow = FakeAirflow(runs=[run], tasks=tasks)

    body = _client(airflow).get("/api/simulate/status").json()

    assert [task["task_id"] for task in body["run"]["tasks"]] == ["send_traffic", "compute_drift"]
    assert body["run"]["tasks"][1]["state"] == "running"
    assert airflow.fetched == [(TRAFFIC_DAG, "manual__2026")]


def test_status_asks_airflow_for_no_tasks_when_no_run_exists():
    airflow = FakeAirflow(runs=[])

    _client(airflow).get("/api/simulate/status")

    assert airflow.fetched == []


def test_status_before_any_traffic_was_ever_sent_is_not_an_error():
    response = _client(FakeAirflow(runs=[])).get("/api/simulate/status")

    assert response.status_code == 200
    assert response.json()["run"] is None
