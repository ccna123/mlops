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

CHAMPION_ALIAS = "champion"

MODEL_TASK_TYPES = {
    "house_price_regressor": "regression",
    "house_needs_renovation_classifier": "classification",
}


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

        Example:
            list_models()
            # -> regression versions carry rmse/mae/r2,
            #    classification versions carry auc/f1/accuracy
        """
        result: list[dict] = []
        for registered in self._client.search_registered_models():
            champion_version = None
            try:
                champion_version = self._client.get_model_version_by_alias(
                    registered.name, CHAMPION_ALIAS
                ).version
            except Exception:  # noqa: BLE001 - no champion yet is a normal state
                champion_version = None

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
            Exception: when the model or version does not exist. The route
                turns that into a 404 rather than reporting a promotion that
                did not happen.

        Example:
            promote("house_price_regressor", "4")
            # -> {"name": "house_price_regressor", "version": "4",
            #     "alias": "champion"}
            # Older versions stay exactly as they were; nothing is archived.
        """
        self._client.set_registered_model_alias(name, CHAMPION_ALIAS, version)
        return {"name": name, "version": version, "alias": CHAMPION_ALIAS}
