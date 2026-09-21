import httpx
import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from services.api.clients.airflow import AirflowClient
from services.api.tests.test_airflow_client import REAL_LOG_LINES, REAL_LOG_TEXT


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


LOG_TEXT = "\n".join(
    [
        "[2026-09-20 10:00:01] INFO - reading raw data",
        "[2026-09-20 10:00:02] WARNING - 3 rows dropped",
        "[2026-09-20 10:00:03] ERROR - could not parse zipcode",
        "[2026-09-20 10:00:04] INFO - wrote 200000 rows",
    ]
)


class FakeAirflowLogs(FakeAirflow):
    def __init__(self, text=LOG_TEXT):
        super().__init__()
        self.text = text
        self.asked = []

    def get_logs(self, dag_id, run_id, task_id, try_number):
        self.asked.append((dag_id, run_id, task_id, try_number))
        return self.text


def test_logs_return_every_line_when_no_filter_is_given():
    airflow = FakeAirflowLogs()
    body = _client(airflow).get("/api/pipeline/runs/r1/logs?stage=extract").json()
    assert len(body["lines"]) == 4
    assert body["truncated"] is False
    assert airflow.asked == [("ml_pipeline", "r1", "extract", 1)]


def test_logs_filter_by_level():
    body = (
        _client(FakeAirflowLogs())
        .get("/api/pipeline/runs/r1/logs?stage=extract&level=ERROR")
        .json()
    )
    assert len(body["lines"]) == 1
    assert "could not parse zipcode" in body["lines"][0]


def test_logs_filter_by_keyword_case_insensitively():
    body = (
        _client(FakeAirflowLogs())
        .get("/api/pipeline/runs/r1/logs?stage=extract&q=ZIPCODE")
        .json()
    )
    assert len(body["lines"]) == 1


def test_logs_level_filter_matches_whole_word_only():
    text = "\n".join(
        [
            "[2026-09-20 10:00:01] INFO - no errors found",
            "[2026-09-20 10:00:02] ERROR - could not parse zipcode",
        ]
    )
    body = (
        _client(FakeAirflowLogs(text=text))
        .get("/api/pipeline/runs/r1/logs?stage=extract&level=ERROR")
        .json()
    )
    assert len(body["lines"]) == 1
    assert "could not parse zipcode" in body["lines"][0]


def test_logs_level_filter_does_not_match_a_word_containing_it():
    text = "\n".join(
        [
            "[2026-09-20 10:00:01] INFO - reading raw data",
            "[2026-09-20 10:00:02] INFORMATION - deprecated field seen",
        ]
    )
    body = (
        _client(FakeAirflowLogs(text=text))
        .get("/api/pipeline/runs/r1/logs?stage=extract&level=INFO")
        .json()
    )
    assert len(body["lines"]) == 1
    assert "reading raw data" in body["lines"][0]


def test_logs_keyword_filter_is_free_text_not_level_matching():
    text = "\n".join(
        [
            "[2026-09-20 10:00:01] INFO - no errors found",
            "[2026-09-20 10:00:02] WARNING - 3 rows dropped",
        ]
    )
    body = (
        _client(FakeAirflowLogs(text=text))
        .get("/api/pipeline/runs/r1/logs?stage=extract&q=error")
        .json()
    )
    assert len(body["lines"]) == 1
    assert "no errors found" in body["lines"][0]


def test_logs_preserve_blank_lines_when_unfiltered():
    text = "\n".join(
        [
            "[2026-09-20 10:00:01] ERROR - traceback follows",
            "",
            "[2026-09-20 10:00:02] INFO - end of traceback",
        ]
    )
    body = (
        _client(FakeAirflowLogs(text=text)).get("/api/pipeline/runs/r1/logs?stage=extract").json()
    )
    assert body["lines"] == [
        "[2026-09-20 10:00:01] ERROR - traceback follows",
        "",
        "[2026-09-20 10:00:02] INFO - end of traceback",
    ]


def test_logs_report_truncation_rather_than_hiding_it():
    long_text = "\n".join(f"[2026-09-20] INFO - line {i}" for i in range(3000))
    body = (
        _client(FakeAirflowLogs(text=long_text))
        .get("/api/pipeline/runs/r1/logs?stage=extract")
        .json()
    )
    assert body["truncated"] is True
    assert len(body["lines"]) == 2000


def test_logs_require_a_stage():
    response = _client(FakeAirflowLogs()).get("/api/pipeline/runs/r1/logs")
    assert response.status_code == 422


def _real_airflow(handler):
    """The real AirflowClient over a scripted transport: real httpx, no network."""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)


def _logs_handler(seen):
    """Plays Airflow's log endpoint, recording each request's Accept header."""

    def handler(request):
        seen.append(request.headers["accept"])
        if request.headers["accept"] == "application/json":
            content = repr([("e59fd8ef0e61", REAL_LOG_TEXT)])
            return httpx.Response(200, json={"content": content, "continuation_token": None})
        return httpx.Response(200, text=REAL_LOG_TEXT, headers={"content-type": "text/plain"})

    return handler


def test_logs_route_returns_the_lines_of_a_real_text_plain_airflow_log():
    seen = []
    client = _client(_real_airflow(_logs_handler(seen)))

    response = client.get("/api/pipeline/runs/r1/logs?stage=extract")

    assert response.status_code == 200
    assert response.json() == {"lines": REAL_LOG_LINES, "truncated": False}
    assert seen == ["text/plain"]


def test_logs_route_filters_real_airflow_lines_by_level():
    client = _client(_real_airflow(_logs_handler([])))

    info = client.get("/api/pipeline/runs/r1/logs?stage=extract&level=INFO").json()["lines"]
    warning = client.get("/api/pipeline/runs/r1/logs?stage=extract&level=WARNING").json()["lines"]

    # The host line, the "Found local files" banner and the WARNING line are
    # not INFO. "DeprecationWarning" inside the WARNING line is not a level.
    assert info == [line for line in REAL_LOG_LINES if " INFO - " in line]
    assert len(info) == 4
    assert warning == [line for line in REAL_LOG_LINES if " WARNING - " in line]
    assert len(warning) == 1


def test_logs_route_searches_real_airflow_lines_by_keyword():
    client = _client(_real_airflow(_logs_handler([])))

    body = client.get("/api/pipeline/runs/r1/logs?stage=extract&q=fingerprint").json()

    assert len(body["lines"]) == 1
    assert body["lines"][0].endswith(
        'XCOM_RESULT {"fingerprint": "3b318b364660175f", "row_count": 1000}'
    )
    assert body["truncated"] is False


def _not_found(request):
    return httpx.Response(404, json={"detail": "not found", "status": 404})


def _server_error(request):
    return httpx.Response(500, text="boom")


def _unauthorized(request):
    return httpx.Response(401, json={"detail": None, "status": 401})


def _unreachable(request):
    raise httpx.ConnectError("connection refused", request=request)


RUN_PATHS = [
    "/api/pipeline/runs/does-not-exist",
    "/api/pipeline/runs/does-not-exist/logs?stage=extract",
]


@pytest.mark.parametrize("path", RUN_PATHS)
def test_a_run_airflow_does_not_know_is_404_with_a_message(path):
    response = _client(_real_airflow(_not_found)).get(path)

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


@pytest.mark.parametrize("path", RUN_PATHS)
@pytest.mark.parametrize(
    "handler", [_server_error, _unauthorized, _unreachable], ids=["5xx", "401", "unreachable"]
)
def test_airflow_failing_for_another_reason_is_a_500_not_a_404(handler, path):
    # A dead Airflow and a missing run must stay distinguishable.
    client = TestClient(create_app(airflow=_real_airflow(handler)), raise_server_exceptions=False)

    assert client.get(path).status_code == 500


def test_a_404_from_airflow_on_the_list_and_trigger_routes_is_still_a_500():
    # Those two routes have no "unknown run" to report: a 404 from Airflow
    # there means the DAG is missing, which is a server-side problem.
    app = create_app(airflow=_real_airflow(_not_found))
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/api/pipeline/runs").status_code == 500
    assert client.post("/api/pipeline/run", json={"task_type": "regression"}).status_code == 500


# --- caller-supplied path parts must not steer the outbound Airflow request --


def _recording_airflow():
    """A real AirflowClient whose transport records every URL and answers 200 text."""
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, text="log text", headers={"content-type": "text/plain"})

    return _real_airflow(handler), seen


@pytest.mark.parametrize(
    "stage",
    [
        "../../variables?",
        "../../../../../variables?",
        "..",
        ".",
        "a/b",
        "a?b",
        "a b",
        "-leading-dash",
        "",
        "x" * 251,
    ],
)
def test_a_stage_that_is_not_a_task_id_is_422_and_sends_nothing(stage):
    airflow, seen = _recording_airflow()

    response = _client(airflow).get("/api/pipeline/runs/anyrun/logs", params={"stage": stage})

    assert response.status_code == 422
    assert seen == []


@pytest.mark.parametrize(
    "stage", ["extract", "prepare_dataset_for_train", "train-model", "_x", "0abc", "a" * 250]
)
def test_real_looking_task_ids_are_accepted(stage):
    airflow, seen = _recording_airflow()

    response = _client(airflow).get("/api/pipeline/runs/anyrun/logs", params={"stage": stage})

    assert response.status_code == 200
    assert len(seen) == 1


def test_a_run_id_carrying_a_question_mark_stays_inside_the_run_path():
    airflow, seen = _recording_airflow()

    # %3F decodes to "?" before the route sees it; unencoded it would start a
    # query string and the request would go to /variables.
    _client(airflow).get("/api/pipeline/runs/x%3F/logs?stage=extract")

    (url,) = seen
    assert url.query == b""
    assert url.raw_path == b"/api/v1/dags/ml_pipeline/dagRuns/x%3F/taskInstances/extract/logs/1"


def test_a_real_run_id_reaches_airflow_encoded():
    airflow, seen = _recording_airflow()
    run_id = "manual__2026-09-21T03:53:17.127926+00:00"

    response = _client(airflow).get(f"/api/pipeline/runs/{run_id}/logs?stage=extract")

    assert response.status_code == 200
    assert seen[0].raw_path == (
        b"/api/v1/dags/ml_pipeline/dagRuns/manual__2026-09-21T03%3A53%3A17.127926%2B00%3A00"
        b"/taskInstances/extract/logs/1"
    )


@pytest.mark.parametrize("run_id", ["%2e%2e", "%2E"])
@pytest.mark.parametrize("suffix", ["", "/logs?stage=extract"])
def test_a_dots_only_run_id_is_404_like_any_unknown_run_and_sends_nothing(run_id, suffix):
    airflow, seen = _recording_airflow()

    response = _client(airflow).get(f"/api/pipeline/runs/{run_id}{suffix}")

    assert response.status_code == 404
    assert seen == []
