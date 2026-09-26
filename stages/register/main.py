"""Register stage: promote the model and snapshot what it learned from.

Promotion moves an alias, not a stage: MLflow deprecated model stages in 2.x and
removes them in 3.x. Moving the `champion` alias to a new version leaves every
older version intact and untouched — nothing is archived, it simply stops being
pointed at.

The version that held the alias before is reported, so `deploy` can move the
alias back if the prediction service cannot serve the new one (CN-13).
"""

from __future__ import annotations

import json
import os
import sys

import mlflow
import mlflow.artifacts
from mlflow import MlflowClient

from ml_common import lineage, schema
from ml_common.model_card import build_model_card
from ml_common.profiling import compute_profile
from ml_common.stageio import emit_result
from ml_common.storage import Storage, baseline_key, processed_key


def sample_record(storage: Storage, data_id: str, task_type: str) -> dict:
    """Takes one raw record from the test set, for deploy's smoke test.

    Args:
        storage: where the test set lives.
        data_id: the data ID of this run.
        task_type: "regression" or "classification".

    Returns:
        The first test record without its target, as it was stored (raw), with
        missing values as None so it survives JSON.

    Example:
        sample_record(storage, "3f0a...", "regression")
        # -> {"property_id": "p9", "city": " NEW YORK", "list_price": "$450,000", ...}
    """
    head, _ = storage.read_parquet_head(processed_key(data_id, task_type, "test"), 1)
    record = head.drop(columns=[schema.target_column(task_type)])
    # pandas' own encoder turns NaN into null and numpy scalars into numbers.
    return json.loads(record.to_json(orient="records"))[0]


def main() -> int:
    """Promotes the model to champion, and writes its baseline profile and model card.

    Only ever reached when `evaluate` said both gates passed.

    Args:
        None. Reads FINGERPRINT (the data ID), TASK_TYPE, MODEL_NAME, RUN_ID and
        MLFLOW_TRACKING_URI, plus the MinIO variables `Storage.from_env` needs.

    Returns:
        0. The stage result carries the new `version`, the `previous_version`
        that held the alias before (None if there was none), the
        `baseline_key`, and a raw `sample_record` for deploy's smoke test. The
        baseline comes from the TRAIN set, so monitoring compares production
        traffic against the distribution the model actually saw. The model card
        is logged as `model_card.json` on the training run.

    Raises:
        KeyError: when a required variable is unset.
        FileNotFoundError: when the train or test set for that data ID and task
            is not in storage.
    """
    data_id = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    run_id = os.environ["RUN_ID"]

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()
    storage = Storage.from_env()

    previous = lineage.champion_version(client, model_name)
    previous_version = str(previous.version) if previous is not None else None

    registered = mlflow.register_model(f"runs:/{run_id}/model", model_name)
    version = registered.version
    print(f"registered {model_name} version {version}", file=sys.stderr)

    client.set_registered_model_alias(model_name, lineage.CHAMPION_ALIAS, version)
    print(
        f"alias {lineage.CHAMPION_ALIAS} now points at version {version} "
        f"(was {previous_version})",
        file=sys.stderr,
    )

    train_df = storage.read_parquet(processed_key(data_id, task_type, "train"))
    profile = compute_profile(train_df, schema.feature_columns(task_type))
    destination = baseline_key(model_name, version)
    storage.write_json(profile, destination)
    print(f"baseline profile written to {destination}", file=sys.stderr)

    run = client.get_run(run_id)
    test_metrics = {
        name[len("test_") :]: value
        for name, value in run.data.metrics.items()
        if name.startswith("test_")
    }
    try:
        groups = mlflow.artifacts.load_dict(f"runs:/{run_id}/group_metrics.json")
    except Exception as error:  # noqa: BLE001 - an older run has no such artifact
        print(f"no group metrics on the run: {error}", file=sys.stderr)
        groups = None
    card = build_model_card(
        model_name=model_name,
        version=str(version),
        task_type=task_type,
        params=dict(run.data.params),
        test_metrics=test_metrics,
        group_metrics=groups,
    )
    with mlflow.start_run(run_id=run_id):
        mlflow.log_dict(card, "model_card.json")
    print("model card logged", file=sys.stderr)

    emit_result(
        {
            "version": str(version),
            "previous_version": previous_version,
            "baseline_key": destination,
            "sample_record": sample_record(storage, data_id, task_type),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
