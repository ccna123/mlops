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
        return self._objects[key]

    def list_keys(self, prefix):
        return sorted(k for k in self._objects if k.startswith(prefix))


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
        drift_summary_key(REGRESSOR, "20260920T0700"): {**SUMMARY, "run_id": "a"},
        drift_summary_key(REGRESSOR, "20260920T0800"): {**SUMMARY, "run_id": "b"},
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
        drift_summary_key(REGRESSOR, f"run{i}"): {**SUMMARY, "run_id": str(i)} for i in range(5)
    }
    client = ReportsClient(FakeStorage(objects))
    assert len(client.history(REGRESSOR, limit=2)) == 2


def test_history_route_passes_the_limit_through_and_keeps_newest_first():
    objects = {
        drift_summary_key(REGRESSOR, f"run{i}"): {**SUMMARY, "run_id": str(i)} for i in range(5)
    }
    body = _client(objects).get(f"/api/drift/history?model_name={REGRESSOR}&limit=2").json()

    assert [item["run_id"] for item in body["history"]] == ["4", "3"]


def test_history_route_defaults_to_twenty_items():
    objects = {
        drift_summary_key(REGRESSOR, f"run{i:02d}"): {**SUMMARY, "run_id": str(i)}
        for i in range(25)
    }
    body = _client(objects).get(f"/api/drift/history?model_name={REGRESSOR}").json()

    assert len(body["history"]) == 20
    assert body["history"][0]["run_id"] == "24"


def test_history_for_one_model_never_contains_another_models_items():
    objects = {
        drift_summary_key(REGRESSOR, "run1"): {**SUMMARY, "run_id": "r1"},
        drift_summary_key(REGRESSOR, "run2"): {**SUMMARY, "run_id": "r2"},
        drift_summary_key(CLASSIFIER, "run3"): {
            **SUMMARY,
            "model_name": CLASSIFIER,
            "run_id": "c3",
        },
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
