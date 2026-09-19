"""Train stage: fit the whole Pipeline and log it to MLflow.

What gets logged is the Pipeline, not the bare estimator. The Pipeline carries
its own cleaning steps, so the model in the Registry knows how to handle a raw
record and serving never needs a second copy of that logic.
"""

from __future__ import annotations

import os
import sys

import mlflow
import mlflow.sklearn
from ml_common import schema
from ml_common.estimators import build_estimator
from ml_common.features import build_pipeline
from ml_common.metrics import compute_metrics
from ml_common.stageio import emit_result
from ml_common.storage import Storage, processed_key


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    estimator_name = os.environ.get("ESTIMATOR_NAME", "ridge")

    storage = Storage.from_env()
    train_df = storage.read_parquet(processed_key(fingerprint, "train"))
    target = schema.target_column(task_type)

    # Drop the target so X looks exactly like a serving record does: no target.
    features = train_df.drop(columns=[target])
    y = train_df[target]
    print(f"training on {len(train_df)} rows, estimator={estimator_name}", file=sys.stderr)

    estimator = build_estimator(task_type, estimator_name)
    pipeline = build_pipeline(task_type, estimator)

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(model_name)

    with mlflow.start_run() as run:
        pipeline.fit(features, y)

        mlflow.log_params(
            {
                "task_type": task_type,
                "estimator": estimator_name,
                "fingerprint": fingerprint,
                "train_rows": len(train_df),
            }
        )
        train_metrics = compute_metrics(task_type, y, pipeline.predict(features))
        mlflow.log_metrics({f"train_{name}": value for name, value in train_metrics.items()})
        # MLflow 2.x uses `artifact_path`; the `name` parameter only exists from MLflow 3.
        mlflow.sklearn.log_model(pipeline, artifact_path="model")

        run_id = run.info.run_id

    print(f"run_id={run_id} train_metrics={train_metrics}", file=sys.stderr)
    emit_result({"run_id": run_id, "experiment": model_name, "metrics": train_metrics})
    return 0


if __name__ == "__main__":
    sys.exit(main())
