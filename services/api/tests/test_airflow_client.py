import json

import pytest

from services.api.clients.airflow import AirflowClient, AirflowNotFoundError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    """Records requests instead of making them."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_trigger_run_posts_conf_and_returns_the_run_id():
    http = FakeHttp([FakeResponse({"dag_run_id": "manual__2026", "state": "queued"})])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    result = client.trigger_run("ml_pipeline", {"task_type": "regression"})

    method, url, kwargs = http.calls[0]
    assert method == "POST"
    assert url == "http://airflow:8080/api/v1/dags/ml_pipeline/dagRuns"
    assert kwargs["json"]["conf"] == {"task_type": "regression"}
    assert result == {"run_id": "manual__2026", "dag_id": "ml_pipeline", "state": "queued"}


def test_every_request_carries_basic_auth():
    http = FakeHttp([FakeResponse({"dag_run_id": "r", "state": "queued"})])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "secret", http=http)

    client.trigger_run("ml_pipeline", {})

    assert http.calls[0][2]["auth"] == ("admin", "secret")


def test_list_runs_normalises_the_fields_the_dashboard_needs():
    http = FakeHttp(
        [
            FakeResponse(
                {
                    "dag_runs": [
                        {
                            "dag_run_id": "r1",
                            "state": "success",
                            "start_date": "2026-09-20T10:00:00+00:00",
                            "end_date": "2026-09-20T10:09:00+00:00",
                            "conf": {"task_type": "regression"},
                        }
                    ]
                }
            )
        ]
    )
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    runs = client.list_runs("ml_pipeline", limit=5)

    assert runs == [
        {
            "run_id": "r1",
            "state": "success",
            "task_type": "regression",
            "started_at": "2026-09-20T10:00:00+00:00",
            "ended_at": "2026-09-20T10:09:00+00:00",
        }
    ]


def test_list_runs_survives_a_run_with_no_conf():
    # A run triggered from the Airflow UI with no config has conf {}.
    http = FakeHttp(
        [
            FakeResponse(
                {
                    "dag_runs": [
                        {
                            "dag_run_id": "r1",
                            "state": "running",
                            "start_date": "2026-09-20T10:00:00+00:00",
                            "end_date": None,
                            "conf": {},
                        }
                    ]
                }
            )
        ]
    )
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    runs = client.list_runs("ml_pipeline", limit=5)

    assert runs[0]["task_type"] is None
    assert runs[0]["ended_at"] is None


def test_list_runs_asks_for_newest_first():
    http = FakeHttp([FakeResponse({"dag_runs": []})])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    client.list_runs("ml_pipeline", limit=7)

    params = http.calls[0][2]["params"]
    assert params["limit"] == 7
    assert params["order_by"] == "-start_date"


def test_get_run_returns_task_states():
    http = FakeHttp(
        [
            FakeResponse({"dag_run_id": "r1", "state": "running"}),
            FakeResponse(
                {
                    "task_instances": [
                        {
                            "task_id": "extract",
                            "state": "success",
                            "try_number": 1,
                            "duration": 12.5,
                        },
                        {
                            "task_id": "validate",
                            "state": "running",
                            "try_number": 1,
                            "duration": None,
                        },
                    ]
                }
            ),
        ]
    )
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    run = client.get_run("ml_pipeline", "r1")

    assert http.calls[0][1] == "http://airflow:8080/api/v1/dags/ml_pipeline/dagRuns/r1"
    assert (
        http.calls[1][1]
        == "http://airflow:8080/api/v1/dags/ml_pipeline/dagRuns/r1/taskInstances"
    )
    assert run["run_id"] == "r1"
    assert run["state"] == "running"
    assert run["tasks"] == [
        {"task_id": "extract", "state": "success", "try_number": 1, "duration": 12.5},
        {"task_id": "validate", "state": "running", "try_number": 1, "duration": None},
    ]


# Copied from the log Airflow 2.10.3 really served for the extract task of
# run manual__2026-09-21T03:53:17.127926+00:00 (Task 12 live measurement). The
# first line is the worker host, then the "Found local files" banner.
REAL_LOG_LINES = [
    "e59fd8ef0e61",
    "*** Found local files:",
    "***   * /opt/airflow/logs/dag_id=ml_pipeline/run_id=manual__2026-09-21T03:53:17.127926"
    "+00:00/task_id=extract/attempt=1.log",
    "[2026-09-21T03:53:17.963+0000] {logging_mixin.py:190} WARNING - "
    "/home/airflow/.local/lib/python3.12/site-packages/airflow/task/task_runner/"
    "standard_task_runner.py:70 DeprecationWarning: This process (pid=944) is "
    "multi-threaded, use of fork() may lead to deadlocks in the child.",
    "[2026-09-21T03:53:18.210+0000] {docker.py:367} INFO - "
    "Starting docker container from image ml-extract:latest",
    "[2026-09-21T03:53:19.106+0000] {docker.py:438} INFO - "
    "raw=raw/v1/data.parquet etag=9cfee4e676617612895d6162545fade1-28 sample_rows=1000",
    "[2026-09-21T03:53:19.137+0000] {docker.py:438} INFO - "
    "reusing existing extracted/3b318b364660175f/data.parquet",
    "[2026-09-21T03:53:19.138+0000] {docker.py:438} INFO - XCOM_RESULT "
    '{"fingerprint": "3b318b364660175f", "row_count": 1000}',
]
REAL_LOG_TEXT = "\n".join(REAL_LOG_LINES) + "\n"


class FakeTextResponse:
    """A response shaped like Airflow's log endpoint, JSON parsing included.

    `.json()` really parses the body, as httpx does, so a client that calls it
    on Airflow's text/plain log fails here for the same reason it fails live.
    """

    def __init__(self, text, content_type, status_code=200):
        self.text = text
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeLogHttp:
    """Answers a log request the way Airflow 2.10 does, depending on `Accept`.

    Accept: application/json gives a JSON envelope whose `content` is the
    repr of a list of (host, text) tuples - useless as a log. Anything else
    (text/plain, or httpx's default */*) gives the plain text body.
    """

    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        accept = kwargs.get("headers", {}).get("Accept", "*/*")
        if accept == "application/json":
            content = repr([("e59fd8ef0e61", REAL_LOG_TEXT)])
            envelope = {"content": content, "continuation_token": None}
            return FakeTextResponse(json.dumps(envelope), "application/json")
        return FakeTextResponse(REAL_LOG_TEXT, "text/plain")


def test_get_logs_returns_the_text_plain_body_as_is():
    http = FakeLogHttp()
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    text = client.get_logs("ml_pipeline", "r1", "extract", 1)

    assert text == REAL_LOG_TEXT
    assert "taskInstances/extract/logs/1" in http.calls[0][1]


def test_get_logs_asks_airflow_for_text_plain():
    # Without this header Airflow's answer depends on what the client happens
    # to send by default; with application/json the log arrives as a repr.
    http = FakeLogHttp()
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    client.get_logs("ml_pipeline", "r1", "extract", 1)

    assert http.calls[0][2]["headers"]["Accept"] == "text/plain"


def test_other_calls_still_expect_json():
    # The Accept header is for the log call only; the JSON endpoints keep the
    # default, so a stray text/plain there would break them.
    http = FakeHttp([FakeResponse({"dag_runs": []})])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    client.list_runs("ml_pipeline", limit=1)

    assert "Accept" not in http.calls[0][2].get("headers", {})


def test_an_http_error_propagates_rather_than_being_swallowed():
    http = FakeHttp([FakeResponse({"detail": "boom"}, status_code=500)])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    with pytest.raises(RuntimeError):
        client.get_run("ml_pipeline", "r1")


def test_get_run_of_a_run_airflow_does_not_know_raises_not_found():
    http = FakeHttp([FakeResponse({"detail": "not found"}, status_code=404)])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    with pytest.raises(AirflowNotFoundError, match="does-not-exist"):
        client.get_run("ml_pipeline", "does-not-exist")


def test_get_run_not_found_on_the_task_instances_call_is_also_not_found():
    # The run can be deleted between the two requests.
    http = FakeHttp(
        [
            FakeResponse({"dag_run_id": "r1", "state": "running"}),
            FakeResponse({"detail": "not found"}, status_code=404),
        ]
    )
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    with pytest.raises(AirflowNotFoundError):
        client.get_run("ml_pipeline", "r1")


def test_get_logs_for_a_run_airflow_does_not_know_raises_not_found():
    http = FakeHttp([FakeTextResponse("not found", "text/plain", status_code=404)])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    with pytest.raises(AirflowNotFoundError, match="does-not-exist"):
        client.get_logs("ml_pipeline", "does-not-exist", "extract", 1)


@pytest.mark.parametrize("status_code", [401, 500, 503])
def test_get_logs_failing_for_another_reason_is_not_not_found(status_code):
    http = FakeHttp([FakeTextResponse("nope", "text/plain", status_code=status_code)])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    with pytest.raises(RuntimeError) as raised:
        client.get_logs("ml_pipeline", "r1", "extract", 1)

    assert not isinstance(raised.value, AirflowNotFoundError)


def test_list_runs_and_trigger_run_keep_propagating_a_404_unchanged():
    # A 404 on these two means the DAG is missing, not that a run is: it stays
    # the generic error so the routes answer 500, exactly as before.
    for call in (
        lambda c: c.list_runs("ml_pipeline", limit=5),
        lambda c: c.trigger_run("ml_pipeline", {}),
    ):
        http = FakeHttp([FakeResponse({"detail": "not found"}, status_code=404)])
        client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

        with pytest.raises(RuntimeError) as raised:
            call(client)

        assert not isinstance(raised.value, AirflowNotFoundError)
