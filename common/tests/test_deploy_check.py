"""The DAG's deploy smoke test. It lives in dags/ (stdlib only) and is loaded by path."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "dags" / "deploy_check.py"
_spec = importlib.util.spec_from_file_location("deploy_check", _PATH)
deploy_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy_check)

SERVING = "http://serving:8000"
MLFLOW = "http://mlflow:5000"


class FakeHttp:
    def __init__(self, served="4", predicted="4", predict_status=200):
        self.served = served
        self.predicted = predicted
        self.predict_status = predict_status
        self.calls = []

    def __call__(self, method, url, body=None):
        self.calls.append((method, url, body))
        if url.endswith("/reload"):
            return 200, {"models": {"regression": {"version": self.served}}}
        if "/predict/" in url:
            return self.predict_status, {"model_version": self.predicted}
        return 200, {}


def _deploy(http, previous="3"):
    return deploy_check.deploy_with_smoke_test(
        task_type="regression", model_name="m", new_version="4",
        previous_version=previous, sample_record={"city": "x"},
        serving_url=SERVING, mlflow_url=MLFLOW, http=http,
    )


def test_a_healthy_deploy_passes_and_sends_the_raw_record():
    http = FakeHttp()
    assert _deploy(http) == {"deployed": "4"}
    assert ("POST", f"{SERVING}/predict/regression", {"city": "x"}) in http.calls
    assert not any("alias" in url for _, url, _ in http.calls)


def test_serving_still_on_the_old_version_rolls_back_to_it():
    http = FakeHttp(served="3")
    with pytest.raises(deploy_check.DeployFailedError) as caught:
        _deploy(http)
    assert caught.value.rolled_back == "3"
    alias_calls = [c for c in http.calls if "alias" in c[1]]
    assert alias_calls == [("POST", f"{MLFLOW}/api/2.0/mlflow/registered-models/alias",
                            {"name": "m", "alias": "champion", "version": "3"})]
    assert http.calls[-1] == ("POST", f"{SERVING}/reload", None)


def test_a_failing_prediction_rolls_back():
    with pytest.raises(deploy_check.DeployFailedError, match="HTTP 500"):
        _deploy(FakeHttp(predict_status=500))


def test_no_previous_champion_removes_the_alias():
    http = FakeHttp(served=None)
    with pytest.raises(deploy_check.DeployFailedError):
        _deploy(http, previous=None)
    assert ("DELETE", f"{MLFLOW}/api/2.0/mlflow/registered-models/alias",
            {"name": "m", "alias": "champion"}) in http.calls


def test_unreachable_serving_is_a_failed_smoke_test():
    def down(method, url, body=None):
        if "serving" in url:
            raise OSError("connection refused")
        return 200, {}

    with pytest.raises(deploy_check.DeployFailedError, match="could not be reached"):
        _deploy(down)
