import pytest

from services.api.clients.airflow import AirflowClient


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


def test_get_logs_returns_the_raw_text():
    http = FakeHttp([FakeResponse({"content": "line one\nline two"})])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    text = client.get_logs("ml_pipeline", "r1", "extract", 1)

    assert text == "line one\nline two"
    assert "taskInstances/extract/logs/1" in http.calls[0][1]


def test_an_http_error_propagates_rather_than_being_swallowed():
    http = FakeHttp([FakeResponse({"detail": "not found"}, status_code=404)])
    client = AirflowClient("http://airflow:8080/api/v1", "admin", "admin", http=http)

    with pytest.raises(RuntimeError):
        client.get_run("ml_pipeline", "missing")
