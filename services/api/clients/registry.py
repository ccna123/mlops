"""Reads the MLflow Model Registry and moves the champion alias.

Metrics are reported as whatever keys the run actually logged. Section 8.1
of the design doc names hardcoding accuracy and f1 as a defect of the old
frontend: regression has rmse, mae and r2, classification has auc, f1 and
accuracy, and a fixed list is wrong for one of them whichever list you pick.

Promotion moves an alias, never a stage. MLflow deprecated stages in 2.x and
removes them in 3.x.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INVALID_PARAMETER_VALUE, RESOURCE_DOES_NOT_EXIST, ErrorCode

CHAMPION_ALIAS = "champion"

# MlflowException.error_code is always the enum's name as a string.
NOT_FOUND_CODE = ErrorCode.Name(RESOURCE_DOES_NOT_EXIST)
INVALID_PARAMETER_CODE = ErrorCode.Name(INVALID_PARAMETER_VALUE)

MODEL_TASK_TYPES = {
    "house_price_regressor": "regression",
    "house_needs_renovation_classifier": "classification",
}


class RegistryNotFoundError(Exception):
    """The registered model or model version does not exist in the Registry.

    The one failure the routes turn into a 404. Anything else MLflow raises
    (it is down, it timed out, it rejected the request) is not "not found"
    and must not be reported as such.
    """


def _is_missing_alias(err: MlflowException) -> bool:
    """Tells "this model has no champion alias" from a genuine failure.

    Args:
        err: the exception `get_model_version_by_alias` raised.

    Returns:
        True when MLflow said the alias, model or version does not exist.
        Observed against MLflow 2.22: a missing alias comes back as
        INVALID_PARAMETER_VALUE with "not found" in the message, not as
        RESOURCE_DOES_NOT_EXIST, so both are accepted. The message check keeps
        other INVALID_PARAMETER_VALUE failures from being read as "no champion".

    Example:
        # alias never set -> True
        # MLflow unreachable, or a 500 from the server -> False
    """
    if err.error_code == NOT_FOUND_CODE:
        return True
    return err.error_code == INVALID_PARAMETER_CODE and "not found" in str(err).lower()


class RegistryClient:
    """Talks to the MLflow Model Registry.

    Example:
        client = RegistryClient()
        client.list_models()
        # -> [{"name": "house_price_regressor", "task_type": "regression",
        #      "versions": [{"version": "3", "metrics": {"rmse": ...},
        #                    "is_champion": True, "created_at": "..."}]}]
    """

    def __init__(self, client=None):
        """Opens a Model Registry client.

        Args:
            client: an MlflowClient, or anything with the same surface.
                None builds a real one from MLFLOW_TRACKING_URI. Injected so
                the tests need no MLflow.
        """
        if client is not None:
            self._client = client
        else:
            import mlflow
            from mlflow import MlflowClient

            mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
            self._client = MlflowClient()

    def list_models(self) -> list[dict]:
        """Lists every registered model with its versions and their metrics.

        Args:
            None.

        Returns:
            One entry per model with `name`, `task_type` and `versions`. Each
            version carries `version`, `metrics`, `is_champion` and
            `created_at`. `metrics` holds the keys that run actually logged,
            with the `test_` prefix the evaluate stage adds stripped off - so
            regression and classification legitimately differ.

        Raises:
            MlflowException: when MLflow fails for any reason other than a
                model having no champion alias yet, which is a normal state
                and yields `is_champion: False` on every version.

        Example:
            list_models()
            # -> regression versions carry rmse/mae/r2,
            #    classification versions carry auc/f1/accuracy
        """
        result: list[dict] = []
        for registered in self._client.search_registered_models():
            champion_version = self._champion_version(registered.name)

            versions = []
            for version in self._client.search_model_versions(f"name='{registered.name}'"):
                logged = self._client.get_run(version.run_id).data.metrics
                metrics = {
                    name[len("test_") :]: value
                    for name, value in logged.items()
                    if name.startswith("test_")
                }
                created_at = datetime.fromtimestamp(
                    version.creation_timestamp / 1000, tz=UTC
                ).isoformat()
                versions.append(
                    {
                        "version": str(version.version),
                        "metrics": metrics,
                        "is_champion": str(version.version) == str(champion_version),
                        "created_at": created_at,
                    }
                )
            result.append(
                {
                    "name": registered.name,
                    "task_type": MODEL_TASK_TYPES.get(registered.name),
                    "versions": sorted(versions, key=lambda v: int(v["version"]), reverse=True),
                }
            )
        return result

    def promote(self, name: str, version: str) -> dict:
        """Moves the champion alias onto one version.

        Args:
            name: the registered model.
            version: the version to promote.

        Returns:
            `name`, `version` and `alias`.

        Raises:
            RegistryNotFoundError: when the model or version does not exist
                (MLflow's RESOURCE_DOES_NOT_EXIST). The route turns that into
                a 404 rather than reporting a promotion that did not happen.
            MlflowException: any other MLflow failure, left to propagate so an
                outage is not mistaken for a missing model.

        Example:
            promote("house_price_regressor", "4")
            # -> {"name": "house_price_regressor", "version": "4",
            #     "alias": "champion"}
            # Older versions stay exactly as they were; nothing is archived.
        """
        try:
            self._client.set_registered_model_alias(name, CHAMPION_ALIAS, version)
        except MlflowException as err:
            if err.error_code == NOT_FOUND_CODE:
                raise RegistryNotFoundError(str(err)) from err
            raise
        return {"name": name, "version": version, "alias": CHAMPION_ALIAS}

    def _champion_version(self, name: str) -> str | None:
        """Finds which version of a model currently holds the champion alias.

        Args:
            name: the registered model.

        Returns:
            The champion's version as a string, or None when the alias was
            never set.

        Raises:
            MlflowException: when the lookup fails for a reason other than the
                alias not existing - an outage must not read as "no champion".

        Example:
            _champion_version("house_price_regressor")  # -> "3"
            _champion_version("never_promoted_model")   # -> None
        """
        try:
            return str(self._client.get_model_version_by_alias(name, CHAMPION_ALIAS).version)
        except MlflowException as err:
            if _is_missing_alias(err):
                return None
            raise
