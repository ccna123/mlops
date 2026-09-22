import httpx
import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from services.api.clients.airflow import AirflowClient


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


def test_run_passes_the_chosen_estimator_through():
    airflow = FakeAirflow()

    response = _client(airflow).post(
        "/api/pipeline/run", json={"task_type": "regression", "estimator_name": "xgboost"}
    )

    assert response.status_code == 200
    _, conf = airflow.triggered[0]
    assert conf["estimator_name"] == "xgboost"


def test_run_without_an_estimator_leaves_the_dag_to_pick_its_default():
    airflow = FakeAirflow()

    _client(airflow).post("/api/pipeline/run", json={"task_type": "regression"})

    _, conf = airflow.triggered[0]
    assert conf["estimator_name"] is None


def test_run_rejects_an_estimator_that_belongs_to_the_other_task_type():
    # "random_forest" is offered for classification only. Letting it through
    # would fail deep inside the train container instead of at the request.
    airflow = FakeAirflow()

    response = _client(airflow).post(
        "/api/pipeline/run", json={"task_type": "regression", "estimator_name": "random_forest"}
    )

    assert response.status_code == 422
    assert airflow.triggered == []


def test_run_rejects_an_estimator_nobody_offers():
    airflow = FakeAirflow()

    response = _client(airflow).post(
        "/api/pipeline/run", json={"task_type": "regression", "estimator_name": "catboost"}
    )

    assert response.status_code == 422
    assert airflow.triggered == []


def test_estimators_lists_the_names_each_task_type_offers():
    body = _client(FakeAirflow()).get("/api/estimators").json()

    assert "xgboost" in body["regression"]
    assert "random_forest" in body["classification"]
    assert "random_forest" not in body["regression"]


def test_estimators_marks_the_diagnostic_ones_so_the_ui_can_group_them():
    # The weak and dummy estimators exist to exercise the promotion gates, not
    # to win. The UI needs to tell them apart without hardcoding their names.
    body = _client(FakeAirflow()).get("/api/estimators").json()

    assert set(body["diagnostic"]) == {"hist_gradient_boosting_weak", "dummy"}


def test_estimators_agrees_with_what_the_trainer_actually_accepts():
    from ml_common.estimators import ESTIMATOR_NAMES

    body = _client(FakeAirflow()).get("/api/estimators").json()

    assert body["regression"] == list(ESTIMATOR_NAMES["regression"])
    assert body["classification"] == list(ESTIMATOR_NAMES["classification"])


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


def _real_airflow(handler):
    """The real AirflowClient over a scripted transport: real httpx, no network."""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)


def _not_found(request):
    return httpx.Response(404, json={"detail": "not found", "status": 404})


def _server_error(request):
    return httpx.Response(500, text="boom")


def _unauthorized(request):
    return httpx.Response(401, json={"detail": None, "status": 401})


def _unreachable(request):
    raise httpx.ConnectError("connection refused", request=request)


RUN_PATH = "/api/pipeline/runs/does-not-exist"


def test_a_run_airflow_does_not_know_is_404_with_a_message():
    response = _client(_real_airflow(_not_found)).get(RUN_PATH)

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


@pytest.mark.parametrize(
    "handler", [_server_error, _unauthorized, _unreachable], ids=["5xx", "401", "unreachable"]
)
def test_airflow_failing_for_another_reason_is_a_500_not_a_404(handler):
    # A dead Airflow and a missing run must stay distinguishable.
    client = TestClient(create_app(airflow=_real_airflow(handler)), raise_server_exceptions=False)

    assert client.get(RUN_PATH).status_code == 500


def test_a_404_from_airflow_on_the_list_and_trigger_routes_is_still_a_500():
    # Those two routes have no "unknown run" to report: a 404 from Airflow
    # there means the DAG is missing, which is a server-side problem.
    app = create_app(airflow=_real_airflow(_not_found))
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/api/pipeline/runs").status_code == 500
    assert client.post("/api/pipeline/run", json={"task_type": "regression"}).status_code == 500


# --- caller-supplied path parts must not steer the outbound Airflow request --


def _recording_airflow():
    """A real AirflowClient whose transport records every URL and answers 200."""
    seen = []

    def handler(request):
        seen.append(request.url)
        # get_run makes two calls; one payload carrying both shapes answers both.
        return httpx.Response(
            200, json={"dag_run_id": "r", "state": "success", "task_instances": []}
        )

    return _real_airflow(handler), seen


def test_a_run_id_carrying_a_question_mark_stays_inside_the_run_path():
    airflow, seen = _recording_airflow()

    # %3F decodes to "?" before the route sees it; unencoded it would start a
    # query string and the request would go to /variables.
    _client(airflow).get("/api/pipeline/runs/x%3F")

    assert seen[0].query == b""
    assert seen[0].raw_path == b"/api/v1/dags/ml_pipeline/dagRuns/x%3F"


def test_a_real_run_id_reaches_airflow_encoded():
    airflow, seen = _recording_airflow()
    run_id = "manual__2026-09-21T03:53:17.127926+00:00"

    response = _client(airflow).get(f"/api/pipeline/runs/{run_id}")

    assert response.status_code == 200
    assert seen[0].raw_path == (
        b"/api/v1/dags/ml_pipeline/dagRuns/manual__2026-09-21T03%3A53%3A17.127926%2B00%3A00"
    )


@pytest.mark.parametrize("run_id", ["%2e%2e", "%2E"])
def test_a_dots_only_run_id_is_404_like_any_unknown_run_and_sends_nothing(run_id):
    airflow, seen = _recording_airflow()

    response = _client(airflow).get(f"/api/pipeline/runs/{run_id}")

    assert response.status_code == 404
    assert seen == []
