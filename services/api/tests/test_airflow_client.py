
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


@pytest.mark.parametrize("status_code", [401, 500, 503])
def test_a_call_failing_for_another_reason_is_not_not_found(status_code):
    http = FakeHttp([FakeResponse({"detail": "nope"}, status_code=status_code)])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    with pytest.raises(RuntimeError) as raised:
        client.get_run("ml_pipeline", "r1")

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


# --- path components must not be able to steer the request ------------------
#
# dag_id, run_id and task_id end up inside a URL path. Unencoded, a "?" starts
# a query string and "../" is normalised away by httpx, so a caller-supplied
# value could redirect the authenticated request to any other Airflow
# endpoint (/variables, /config, /connections).

BASE = "http://airflow:8080/api/v1"
REAL_RUN_ID = "manual__2026-09-21T03:53:17.127926+00:00"
REAL_RUN_ID_ENCODED = "manual__2026-09-21T03%3A53%3A17.127926%2B00%3A00"


def _recording_httpx(seen):
    """A real httpx client over a transport that records the URL httpx really sends."""
    import httpx

    def handler(request):
        seen.append(request.url)
        # get_run makes two calls; one payload carrying both shapes answers both.
        return httpx.Response(
            200, json={"dag_run_id": "r", "state": "success", "task_instances": []}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_hostile_component_cannot_leave_the_dag_run_path_as_httpx_sends_it():
    seen = []
    client = AirflowClient(BASE, "admin", "admin", http=_recording_httpx(seen))

    client.get_run("ml_pipeline", "../../../../../variables?x=1")

    url = seen[0]
    assert url.query == b""
    assert url.raw_path == (
        b"/api/v1/dags/ml_pipeline/dagRuns/"
        b"..%2F..%2F..%2F..%2F..%2Fvariables%3Fx%3D1"
    )


def test_get_run_encodes_the_run_id_on_both_requests():
    http = FakeHttp(
        [
            FakeResponse({"dag_run_id": REAL_RUN_ID, "state": "success"}),
            FakeResponse({"task_instances": []}),
        ]
    )
    client = AirflowClient(BASE, "admin", "admin", http=http)

    client.get_run("ml_pipeline", REAL_RUN_ID)

    assert http.calls[0][1] == f"{BASE}/dags/ml_pipeline/dagRuns/{REAL_RUN_ID_ENCODED}"
    assert http.calls[1][1] == (
        f"{BASE}/dags/ml_pipeline/dagRuns/{REAL_RUN_ID_ENCODED}/taskInstances"
    )


def test_trigger_and_list_encode_the_dag_id_too():
    http = FakeHttp(
        [FakeResponse({"dag_runs": []}), FakeResponse({"dag_run_id": "r", "state": "queued"})]
    )
    client = AirflowClient(BASE, "admin", "admin", http=http)

    client.list_runs("a?b", limit=1)
    client.trigger_run("a?b", {})

    assert http.calls[0][1] == f"{BASE}/dags/a%3Fb/dagRuns"
    assert http.calls[1][1] == f"{BASE}/dags/a%3Fb/dagRuns"


@pytest.mark.parametrize("dots", [".", ".."])
def test_a_run_id_of_only_dots_is_not_found_and_sends_nothing(dots):
    # quote() leaves dots alone and httpx would collapse the segment, turning
    # ".../dagRuns/../taskInstances" into a request for a different endpoint.
    http = FakeHttp([])
    client = AirflowClient(BASE, "admin", "admin", http=http)

    with pytest.raises(AirflowNotFoundError, match="no run"):
        client.get_run("ml_pipeline", dots)

    assert http.calls == []
