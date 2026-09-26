"""Deploy with a smoke test, and roll back when the new version is not really serving.

A reload request can succeed while serving still answers with the old model -
for instance when the new one fails to load because the image's libraries do
not match the ones it was trained with. Without a check, the pipeline reports
success, MLflow shows the new version as champion, and serving keeps answering
with the old one (02 3.8, CN-13).

Standard library only: this runs inside the Airflow image, which has neither
ml_common nor the MLflow client. MLflow is reached through its REST API.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

CHAMPION_ALIAS = "champion"


class DeployFailedError(Exception):
    """Raised when the smoke test fails; the alias has already been rolled back.

    Example:
        try:
            deploy_with_smoke_test(...)
        except DeployFailedError as error:
            error.reason       # -> "serving reports version 3, expected 4"
            error.rolled_back  # -> "3"
    """

    def __init__(self, reason: str, rolled_back: str | None):
        """Keeps why the deploy failed and where the alias went back to.

        Args:
            reason: what the smoke test saw.
            rolled_back: the version the alias points at again, or None when
                there was no earlier champion and the alias was removed.
        """
        super().__init__(f"deploy failed: {reason}; champion rolled back to {rolled_back}")
        self.reason = reason
        self.rolled_back = rolled_back


def http_json(method: str, url: str, body: dict | None = None, timeout: float = 30):
    """Sends one JSON request.

    Args:
        method: "GET", "POST" or "DELETE".
        url: the full URL.
        body: sent as JSON when given.
        timeout: seconds.

    Returns:
        `(status, decoded body or None)`. An HTTP error status is returned, not
        raised, so the caller can report it.

    Raises:
        urllib.error.URLError: when the host cannot be reached at all.

    Example:
        http_json("POST", "http://serving:8000/reload")  # -> (200, {"models": ...})
    """
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"detail": raw}


def _served_version(models: dict | None, task_type: str) -> str | None:
    """Reads which version serving says it holds for a task.

    Args:
        models: the `models` block of /reload or /health.
        task_type: the task.

    Returns:
        The version as a string, or None when nothing is loaded.

    Example:
        _served_version({"regression": {"version": "4"}}, "regression")  # -> "4"
    """
    entry = (models or {}).get(task_type) or {}
    version = entry.get("version")
    return None if version is None else str(version)


def smoke_test(*, task_type, new_version, sample_record, serving_url, http=http_json) -> str | None:
    """Reloads serving and checks it really answers with the new version.

    Args:
        task_type: "regression" or "classification".
        new_version: the version register just promoted.
        sample_record: one raw test record.
        serving_url: base URL of the prediction service.
        http: the request function (tests pass a fake).

    Returns:
        None when serving holds the new version AND answers the raw record
        with it; otherwise the reason it did not.

    Example:
        smoke_test(task_type="regression", new_version="4", sample_record=rec,
                   serving_url="http://serving:8000")
        # -> None
    """
    try:
        status, body = http("POST", f"{serving_url}/reload")
    except OSError as error:
        return f"serving could not be reached for reload: {error}"
    if status != 200:
        return f"reload answered HTTP {status}"
    served = _served_version((body or {}).get("models"), task_type)
    if served != str(new_version):
        return f"serving reports version {served}, expected {new_version}"
    try:
        status, body = http("POST", f"{serving_url}/predict/{task_type}", sample_record)
    except OSError as error:
        return f"serving could not be reached for a prediction: {error}"
    if status != 200:
        return f"the sample prediction answered HTTP {status}: {body}"
    answered = str((body or {}).get("model_version"))
    if answered != str(new_version):
        return f"the sample prediction came from version {answered}, expected {new_version}"
    return None


def move_champion(*, model_name, version, mlflow_url, http=http_json) -> None:
    """Points the champion alias at a version, or removes it when version is None.

    Args:
        model_name: the registered model.
        version: the version to point at, or None.
        mlflow_url: base URL of the MLflow tracking server.
        http: the request function.

    Raises:
        RuntimeError: when MLflow refuses.

    Example:
        move_champion(model_name="house_price_regressor", version="3",
                      mlflow_url="http://mlflow:5000")
    """
    base = f"{mlflow_url}/api/2.0/mlflow/registered-models/alias"
    if version is None:
        # MLflow reads a DELETE's parameters from the JSON body (only GET reads
        # the query string).
        status, body = http("DELETE", base, {"name": model_name, "alias": CHAMPION_ALIAS})
    else:
        status, body = http(
            "POST", base, {"name": model_name, "alias": CHAMPION_ALIAS, "version": str(version)}
        )
    if status != 200:
        raise RuntimeError(f"MLflow refused to move the champion alias: HTTP {status} {body}")


def deploy_with_smoke_test(
    *,
    task_type: str,
    model_name: str,
    new_version: str,
    previous_version: str | None,
    sample_record: dict,
    serving_url: str,
    mlflow_url: str,
    http=http_json,
) -> dict:
    """Reloads serving, smoke-tests it, and rolls back when the test fails.

    Args:
        task_type: "regression" or "classification".
        model_name: the registered model.
        new_version: the version register just promoted.
        previous_version: the version that held the alias before, or None.
        sample_record: one raw test record.
        serving_url: base URL of the prediction service.
        mlflow_url: base URL of MLflow.
        http: the request function.

    Returns:
        `{"deployed": new_version}` when the smoke test passed.

    Raises:
        DeployFailedError: when it failed. By then the alias points at
            `previous_version` again (or is removed), and serving has been asked
            to reload once more so it serves that version.

    Example:
        deploy_with_smoke_test(task_type="regression", model_name="house_price_regressor",
                               new_version="4", previous_version="3",
                               sample_record=rec, serving_url="http://serving:8000",
                               mlflow_url="http://mlflow:5000")
        # -> {"deployed": "4"}
    """
    reason = smoke_test(
        task_type=task_type,
        new_version=new_version,
        sample_record=sample_record,
        serving_url=serving_url,
        http=http,
    )
    if reason is None:
        return {"deployed": str(new_version)}
    move_champion(model_name=model_name, version=previous_version, mlflow_url=mlflow_url, http=http)
    try:
        http("POST", f"{serving_url}/reload")
    except OSError:
        pass  # the failure being reported already says serving is in trouble
    raise DeployFailedError(reason, previous_version)
