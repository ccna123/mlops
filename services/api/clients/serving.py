"""Talks to the prediction service, for the few writes that must reach it.

After the operator moves the champion alias or deletes a model by hand, the
prediction service has to reload, or it keeps answering with the model already
in memory - which made a manual rollback look done while doing nothing
(02 5.2, CN-16, CN-18).
"""

from __future__ import annotations

import os

import httpx


class ServingClient:
    """Asks the prediction service to reload its champions.

    Example:
        ServingClient("http://serving:8000").reload()
        # -> {"regression": {"loaded": True, "name": "house_price_regressor",
        #                    "version": "4"}, "classification": {...}}
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        """Remembers where the service is; makes no request.

        Args:
            base_url: the service root. None reads SERVING_URL (default
                http://serving:8000).
            timeout: seconds per request. A reload loads two models from
                MLflow, so it is slower than a health probe.
        """
        self.base_url = (base_url or os.environ.get("SERVING_URL", "http://serving:8000")).rstrip(
            "/"
        )
        self.timeout = timeout

    def reload(self) -> dict:
        """Makes the service re-read the champion of every model.

        Args:
            None.

        Returns:
            The `models` block the service answers with: per task type,
            `loaded`, `name` and the live `version`.

        Raises:
            httpx.HTTPError: when the service cannot be reached or answers an
                error status.

        Example:
            ServingClient().reload()["regression"]["version"]  # -> "4"
        """
        response = httpx.post(f"{self.base_url}/reload", timeout=self.timeout)
        response.raise_for_status()
        return response.json()["models"]


def serving_state_after_change(serving, model_name: str, expected_version: str | None) -> dict:
    """Reloads serving after a manual change and says whether it followed.

    The change in MLflow is kept whatever happens here; this only reports
    whether the prediction service now serves what MLflow says, so the UI never
    reports a full success that did not happen (02 9.1).

    Args:
        serving: a `ServingClient`, or None when none is configured.
        model_name: the registered model that was changed.
        expected_version: the version serving should now hold, or None when
            the model was deleted and serving should hold nothing.

    Returns:
        `{"switched": bool, "version": what serving holds, "error": str|None}`.

    Example:
        serving_state_after_change(client, "house_price_regressor", "3")
        # -> {"switched": True, "version": "3", "error": None}
    """
    if serving is None:
        return {"switched": False, "version": None, "error": "no prediction service configured"}
    try:
        models = serving.reload()
    except Exception as error:  # noqa: BLE001 - any failure is reported, not raised
        return {"switched": False, "version": None, "error": f"serving did not reload: {error}"}
    served = next(
        (entry.get("version") for entry in models.values() if entry.get("name") == model_name),
        None,
    )
    served = None if served is None else str(served)
    switched = served == expected_version
    error = None if switched else f"serving holds version {served}, expected {expected_version}"
    return {"switched": switched, "version": served, "error": error}
