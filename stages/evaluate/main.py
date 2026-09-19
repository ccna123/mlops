"""Evaluate stage: score the candidate and decide whether it may be promoted.

Two gates, both required. The first blocks junk on an absolute threshold. The
second blocks a merely-adequate model from displacing a better one, scored on
the SAME test split — which is why that split has a fixed seed.

A failed gate is a result, not an error: this stage always exits 0 and lets the
DAG branch on what it reports.
"""

from __future__ import annotations

import os
import sys

import mlflow
import mlflow.sklearn
from ml_common import schema
from ml_common.gates import evaluate_gates
from ml_common.metrics import compute_metrics
from ml_common.stageio import emit_result
from ml_common.storage import Storage, processed_key
from mlflow.exceptions import MlflowException

CHAMPION_ALIAS = "champion"


def score_model(model, features, y_true, task_type: str) -> dict:
    """Runs a model over the test split and returns its metrics."""
    y_pred = model.predict(features)
    y_proba = None
    if task_type == "classification" and hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(features)[:, 1]
    return compute_metrics(task_type, y_true, y_pred, y_proba)


def load_champion(model_name: str):
    """Loads the current champion, or None when nothing has been promoted yet."""
    try:
        return mlflow.sklearn.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
    except MlflowException as err:
        print(f"no champion to compare against: {err}", file=sys.stderr)
        return None


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    run_id = os.environ["RUN_ID"]

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])

    storage = Storage.from_env()
    test_df = storage.read_parquet(processed_key(fingerprint, task_type, "test"))
    target = schema.target_column(task_type)
    features = test_df.drop(columns=[target])
    y_true = test_df[target]
    print(f"scoring on {len(test_df)} test rows", file=sys.stderr)

    candidate = mlflow.sklearn.load_model(f"runs:/{run_id}/model")
    candidate_metrics = score_model(candidate, features, y_true, task_type)
    print(f"candidate: {candidate_metrics}", file=sys.stderr)

    champion = load_champion(model_name)
    champion_metrics = None
    if champion is not None:
        champion_metrics = score_model(champion, features, y_true, task_type)
        print(f"champion:  {champion_metrics}", file=sys.stderr)

    decision = evaluate_gates(task_type, candidate_metrics, champion_metrics)
    print(f"decision: {decision['reason']}", file=sys.stderr)

    # Write the numbers back onto the candidate's own run, so a blocked model
    # still leaves a record of why it was blocked.
    with mlflow.start_run(run_id=run_id):
        mlflow.log_metrics({f"test_{name}": value for name, value in candidate_metrics.items()})
        if champion_metrics is not None:
            mlflow.log_metrics(
                {f"champion_test_{name}": value for name, value in champion_metrics.items()}
            )
        mlflow.set_tags(
            {
                "gate_passed": str(decision["passed"]),
                "gate_reason": decision["reason"],
            }
        )

    emit_result(
        {
            "passed": decision["passed"],
            "reason": decision["reason"],
            "metrics": candidate_metrics,
            "champion_metrics": champion_metrics,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
