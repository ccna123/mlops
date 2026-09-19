"""Register stage: promote the model and snapshot what it learned from.

Promotion moves an alias, not a stage: MLflow deprecated model stages in 2.x and
removes them in 3.x. Moving the `champion` alias to a new version leaves every
older version intact and untouched — nothing is archived, it simply stops being
pointed at.
"""

from __future__ import annotations

import os
import sys

import mlflow
from ml_common import schema
from ml_common.profiling import compute_profile
from ml_common.stageio import emit_result
from ml_common.storage import Storage, baseline_key, processed_key
from mlflow import MlflowClient

CHAMPION_ALIAS = "champion"


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    run_id = os.environ["RUN_ID"]

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()

    registered = mlflow.register_model(f"runs:/{run_id}/model", model_name)
    version = registered.version
    print(f"registered {model_name} version {version}", file=sys.stderr)

    client.set_registered_model_alias(model_name, CHAMPION_ALIAS, version)
    print(f"alias {CHAMPION_ALIAS} now points at version {version}", file=sys.stderr)

    # Baseline comes from the TRAIN split: Plan 4 compares production traffic
    # against the distribution the model actually learned from.
    storage = Storage.from_env()
    train_df = storage.read_parquet(processed_key(fingerprint, "train"))
    profile = compute_profile(train_df, schema.feature_columns(task_type))

    destination = baseline_key(model_name, version)
    storage.write_json(profile, destination)
    print(f"baseline profile written to {destination}", file=sys.stderr)

    emit_result({"version": str(version), "baseline_key": destination})
    return 0


if __name__ == "__main__":
    sys.exit(main())
