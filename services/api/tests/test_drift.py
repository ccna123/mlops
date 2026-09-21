import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi.testclient import TestClient

from ml_common.storage import drift_latest_key, drift_summary_key, report_key
from services.api.app import create_app
from services.api.clients.reports import ReportsClient

SUMMARY = {
    "model_name": "house_price_regressor",
    "model_version": "3",
    "task_type": "regression",
    "run_id": "20260920T075645",
    "computed_at": "2026-09-20T07:56:45+00:00",
    "severity": "high",
    "parts": {"feature": "ok", "prediction": "high", "performance": "high"},
    "n_predictions": 500,
    "n_ground_truth": 500,
    "current_metrics": {"rmse": 305791.8, "mae": 184188.3, "r2": 0.567},
    "report_key": "reports/house_price_regressor/20260920T075645/evidently.html",
}

REGRESSOR = "house_price_regressor"
CLASSIFIER = "house_needs_renovation_classifier"


class FakeStorage:
    def __init__(self, objects: dict):
        self._objects = objects

    def exists(self, key):
        return key in self._objects

    def read_json(self, key):
        # The real Storage.read_json raises FileNotFoundError for a missing key.
        if key not in self._objects:
            raise FileNotFoundError(f"Key not found: {key}")
        return self._objects[key]

    def list_keys(self, prefix):
        return sorted(k for k in self._objects if k.startswith(prefix))


def _summary(run_id, computed_at, model_name=REGRESSOR):
    return {**SUMMARY, "model_name": model_name, "run_id": run_id, "computed_at": computed_at}


def _client(objects):
    return TestClient(create_app(reports=ReportsClient(FakeStorage(objects))))


def test_latest_returns_the_summary_plan_4_wrote():
    objects = {drift_latest_key(REGRESSOR): SUMMARY}
    body = _client(objects).get(f"/api/drift/latest?model_name={REGRESSOR}").json()

    assert body["severity"] == "high"
    assert body["parts"]["feature"] == "ok"
    assert body["parts"]["performance"] == "high"


def test_latest_before_monitoring_has_ever_run_is_404():
    response = _client({}).get(f"/api/drift/latest?model_name={REGRESSOR}")
    assert response.status_code == 404


def test_latest_for_one_model_does_not_return_another_models_summary():
    other = {**SUMMARY, "model_name": CLASSIFIER, "severity": "ok"}
    objects = {drift_latest_key(CLASSIFIER): other}
    client = _client(objects)

    assert client.get(f"/api/drift/latest?model_name={REGRESSOR}").status_code == 404
    body = client.get(f"/api/drift/latest?model_name={CLASSIFIER}").json()
    assert body["model_name"] == CLASSIFIER


def test_latest_picks_the_requested_model_when_both_have_one():
    objects = {
        drift_latest_key(REGRESSOR): {**SUMMARY, "severity": "high"},
        drift_latest_key(CLASSIFIER): {**SUMMARY, "model_name": CLASSIFIER, "severity": "ok"},
    }
    body = _client(objects).get(f"/api/drift/latest?model_name={REGRESSOR}").json()
    assert body["severity"] == "high"


def test_history_returns_summaries_newest_first():
    objects = {
        drift_summary_key(REGRESSOR, "20260920T0700"): _summary("a", "2026-09-20T07:00:00+00:00"),
        drift_summary_key(REGRESSOR, "20260920T0800"): _summary("b", "2026-09-20T08:00:00+00:00"),
    }
    body = _client(objects).get(f"/api/drift/history?model_name={REGRESSOR}").json()
    assert [item["run_id"] for item in body["history"]] == ["b", "a"]


def test_history_ignores_objects_that_are_not_summaries():
    objects = {
        drift_latest_key(REGRESSOR): SUMMARY,
        drift_summary_key(REGRESSOR, "20260920T0800"): SUMMARY,
        report_key(REGRESSOR, "20260920T0800", "html"): {"not": "a summary"},
        report_key(REGRESSOR, "20260920T0800", "json"): {"not": "a summary"},
    }
    client = ReportsClient(FakeStorage(objects))
    assert len(client.history(REGRESSOR, limit=10)) == 1


def test_history_honours_the_limit():
    objects = {
        drift_summary_key(REGRESSOR, f"run{i}"): _summary(str(i), f"2026-09-20T0{i}:00:00+00:00")
        for i in range(5)
    }
    client = ReportsClient(FakeStorage(objects))
    assert len(client.history(REGRESSOR, limit=2)) == 2


def test_history_route_passes_the_limit_through_and_keeps_newest_first():
    objects = {
        drift_summary_key(REGRESSOR, f"run{i}"): _summary(str(i), f"2026-09-20T0{i}:00:00+00:00")
        for i in range(5)
    }
    body = _client(objects).get(f"/api/drift/history?model_name={REGRESSOR}&limit=2").json()

    assert [item["run_id"] for item in body["history"]] == ["4", "3"]


def test_history_route_defaults_to_twenty_items():
    objects = {
        drift_summary_key(REGRESSOR, f"run{i:02d}"): _summary(
            str(i), f"2026-09-{i + 1:02d}T00:00:00+00:00"
        )
        for i in range(25)
    }
    body = _client(objects).get(f"/api/drift/history?model_name={REGRESSOR}").json()

    assert len(body["history"]) == 20
    assert body["history"][0]["run_id"] == "24"


def test_history_for_one_model_never_contains_another_models_items():
    objects = {
        drift_summary_key(REGRESSOR, "run1"): _summary("r1", "2026-09-20T01:00:00+00:00"),
        drift_summary_key(REGRESSOR, "run2"): _summary("r2", "2026-09-20T02:00:00+00:00"),
        drift_summary_key(CLASSIFIER, "run3"): _summary(
            "c3", "2026-09-20T03:00:00+00:00", CLASSIFIER
        ),
    }
    client = _client(objects)

    regressor = client.get(f"/api/drift/history?model_name={REGRESSOR}").json()["history"]
    classifier = client.get(f"/api/drift/history?model_name={CLASSIFIER}").json()["history"]

    assert [item["run_id"] for item in regressor] == ["r2", "r1"]
    assert [item["run_id"] for item in classifier] == ["c3"]


def test_history_does_not_mix_in_a_model_whose_name_starts_the_same():
    objects = {
        drift_summary_key(REGRESSOR, "run1"): {**SUMMARY, "run_id": "r1"},
        drift_summary_key(f"{REGRESSOR}_v2", "run2"): {**SUMMARY, "run_id": "v2"},
    }
    body = _client(objects).get(f"/api/drift/history?model_name={REGRESSOR}").json()
    assert [item["run_id"] for item in body["history"]] == ["r1"]


def test_history_with_no_runs_is_an_empty_list_not_an_error():
    response = _client({}).get(f"/api/drift/history?model_name={REGRESSOR}")
    assert response.status_code == 200
    assert response.json()["history"] == []


def test_history_limit_of_zero_is_rejected():
    # limit=0 must not quietly answer "no history".
    response = _client({}).get(f"/api/drift/history?model_name={REGRESSOR}&limit=0")
    assert response.status_code == 422


def test_history_negative_limit_is_rejected():
    # keys[:-1] would otherwise return everything except the newest run.
    objects = {
        drift_summary_key(REGRESSOR, f"run{i}"): {**SUMMARY, "run_id": str(i)} for i in range(3)
    }
    response = _client(objects).get(f"/api/drift/history?model_name={REGRESSOR}&limit=-1")
    assert response.status_code == 422


# Run ids come in three formats: the monitor stage's own default timestamp, and
# the two Airflow shapes monitoring_dag passes through as MONITOR_RUN_ID. Sorted
# by key, "scheduled__" > "manual__" > "2026..." whatever time each ran at.
STAMP_RUN = "20260920T075645"
SCHEDULED_RUN = "scheduled__2026-09-20T07-00-00-00-00"
MANUAL_RUN = "manual__2026-09-20T07-56-45.123456-00-00"


def _mixed_format_objects():
    return {
        drift_summary_key(REGRESSOR, STAMP_RUN): _summary("stamp", "2026-09-20T09:00:00+00:00"),
        drift_summary_key(REGRESSOR, MANUAL_RUN): _summary(
            "manual", "2026-09-20T08:00:00.123456+00:00"
        ),
        drift_summary_key(REGRESSOR, SCHEDULED_RUN): _summary(
            "scheduled", "2026-09-20T07:00:00+00:00"
        ),
    }


def test_history_orders_by_computed_at_not_by_run_id_format():
    # Key order here is scheduled, manual, stamp - the exact reverse of the
    # real chronology, so a sort by key gets every position wrong.
    body = (
        _client(_mixed_format_objects()).get(f"/api/drift/history?model_name={REGRESSOR}").json()
    )
    assert [item["run_id"] for item in body["history"]] == ["stamp", "manual", "scheduled"]


def test_history_limit_cuts_after_sorting_by_computed_at():
    url = f"/api/drift/history?model_name={REGRESSOR}&limit=1"
    body = _client(_mixed_format_objects()).get(url).json()
    assert [item["run_id"] for item in body["history"]] == ["stamp"]


def test_history_puts_a_summary_without_a_usable_computed_at_last():
    no_time = {k: v for k, v in _summary("missing", "unused").items() if k != "computed_at"}
    objects = {
        drift_summary_key(REGRESSOR, "zzz-missing"): no_time,
        drift_summary_key(REGRESSOR, "zzz-garbled"): _summary("garbled", "last tuesday"),
        drift_summary_key(REGRESSOR, "zzz-naive"): _summary("naive", "2026-09-20T12:00:00"),
        drift_summary_key(REGRESSOR, "aaa-old"): _summary("old", "2026-09-20T01:00:00+00:00"),
        drift_summary_key(REGRESSOR, "aaa-new"): _summary("new", "2026-09-20T02:00:00+00:00"),
    }
    body = _client(objects).get(f"/api/drift/history?model_name={REGRESSOR}").json()

    ids = [item["run_id"] for item in body["history"]]
    assert ids[:2] == ["new", "old"]
    assert set(ids[2:]) == {"missing", "garbled", "naive"}


# --- an unreachable object store is not "no drift report yet" ---------------


class ScriptedStorage:
    """Storage whose `read_json` either raises `error` or returns `payload`.

    Records every key `read_json` was asked for, so a test can prove which key
    was read. `exists` behaves like the real `Storage.exists`, which swallows
    every error and answers False: a client that asks it first cannot tell a
    missing key from an unreachable store.
    """

    def __init__(self, error=None, payload=None):
        self.error = error
        self.payload = payload
        self.reads = []

    def exists(self, key):
        return self.error is None

    def read_json(self, key):
        self.reads.append(key)
        if self.error is not None:
            raise self.error
        return self.payload


def _scripted_client(storage, **kwargs):
    return TestClient(create_app(reports=ReportsClient(storage)), **kwargs)


def test_latest_reads_exactly_the_latest_key_of_the_requested_model():
    storage = ScriptedStorage(payload=SUMMARY)

    body = _scripted_client(storage).get(f"/api/drift/latest?model_name={CLASSIFIER}").json()

    assert body == SUMMARY
    assert storage.reads == [drift_latest_key(CLASSIFIER)]


def test_latest_is_404_only_because_the_key_does_not_exist():
    storage = ScriptedStorage(error=FileNotFoundError("Key not found"))

    response = _scripted_client(storage).get(f"/api/drift/latest?model_name={REGRESSOR}")

    assert response.status_code == 404
    assert REGRESSOR in response.json()["detail"]
    assert storage.reads == [drift_latest_key(REGRESSOR)]


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject"),
        EndpointConnectionError(endpoint_url="http://minio:9000"),
        RuntimeError("minio unreachable"),
        KeyError("latest"),
    ],
    ids=["access-denied", "connection-refused", "runtime", "key-error"],
)
def test_latest_when_storage_fails_for_any_other_reason_is_a_500_not_a_404(error):
    # A MinIO outage or bad credentials must not read as "monitoring never ran".
    storage = ScriptedStorage(error=error)

    response = _scripted_client(storage, raise_server_exceptions=False).get(
        f"/api/drift/latest?model_name={REGRESSOR}"
    )

    assert response.status_code == 500


def test_latest_client_returns_none_only_for_a_missing_key_and_propagates_the_rest():
    missing = ReportsClient(ScriptedStorage(error=FileNotFoundError("Key not found")))
    broken = ReportsClient(ScriptedStorage(error=RuntimeError("minio unreachable")))

    assert missing.latest(REGRESSOR) is None
    with pytest.raises(RuntimeError, match="unreachable"):
        broken.latest(REGRESSOR)


class FakeAirflow:
    """Stands in for AirflowClient, recording which DAG the route triggered."""

    def __init__(self):
        self.triggered = []

    def trigger_run(self, dag_id, conf):
        self.triggered.append((dag_id, conf))
        return {"run_id": "manual__2026", "dag_id": dag_id, "state": "queued"}


def test_drift_run_triggers_the_monitoring_dag():
    airflow = FakeAirflow()

    response = TestClient(create_app(airflow=airflow)).post("/api/drift/run")

    assert response.status_code == 200
    assert response.json()["run_id"] == "manual__2026"
    assert airflow.triggered == [("monitoring_dag", {})]


def test_drift_run_monitors_every_model_so_it_takes_no_model_name():
    # monitoring_dag fans out to one task per task_type on its own, so there is
    # no per-model parameter to pass - a model_name here would be a lie.
    airflow = FakeAirflow()

    response = TestClient(create_app(airflow=airflow)).post(
        "/api/drift/run", json={"model_name": REGRESSOR}
    )

    assert response.status_code == 200
    assert airflow.triggered == [("monitoring_dag", {})]
