"""Round-trip check: a model reloaded from MLflow must behave identically.

Spec section 7.11 asks for this. It is the cheapest way to catch training and
serving drifting apart: if the Pipeline that comes back out of the Registry
predicts differently from the one that went in, something in the packaging is
lossy, and Plan 3's /predict would inherit that silently.

Run from the host, with the stack up.
"""

from __future__ import annotations

import os

import mlflow
import mlflow.sklearn
import numpy as np
from mlflow import MlflowClient

from ml_common import schema
from ml_common.storage import Storage, processed_key

os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadmin")

MODEL_NAME = "house_price_regressor"
TASK_TYPE = "regression"
SAMPLE_SIZE = 20


def main() -> int:
    r"""Checks that a model reloaded from the Registry predicts identically.

    Loads the current champion twice — once by its run, once by its alias —
    feeds both the same 20 RAW test records, and compares.

    Args:
        None. Talks to MLflow and MinIO on localhost, so the stack must be up
        and this must be run from the host, not from inside a container.

    Returns:
        0 when both models agree and the predictions are positive dollar
        amounts.

    Raises:
        SystemExit: when the two disagree, or the predictions are not positive.
            Either means the packaging is lossy, and /predict would inherit
            that silently.

    Example:
        #   .venv\Scripts\python.exe scripts\smoke_round_trip.py
        # -> champion is version 3 from run a1b2c3d4
        #    feeding RAW records straight in - no cleaning on this side:
        #      list_price[0] = '$450,000'
        #      city[0]       = '  NEW YORK '
        #    OK: 20 raw records, identical predictions both ways
    """
    mlflow.set_tracking_uri("http://localhost:5000")
    client = MlflowClient()

    version = client.get_model_version_by_alias(MODEL_NAME, "champion")
    print(f"champion is version {version.version} from run {version.run_id}")

    fingerprint = client.get_run(version.run_id).data.params["fingerprint"]
    test_df = Storage.from_env().read_parquet(processed_key(fingerprint, TASK_TYPE, "test"))
    raw_records = test_df.drop(columns=[schema.target_column(TASK_TYPE)]).head(SAMPLE_SIZE)

    print("feeding RAW records straight in — no cleaning on this side:")
    print(f"  list_price[0] = {raw_records['list_price'].iloc[0]!r}")
    print(f"  city[0]       = {raw_records['city'].iloc[0]!r}")

    from_run = mlflow.sklearn.load_model(f"runs:/{version.run_id}/model")
    from_alias = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@champion")

    predictions_from_run = from_run.predict(raw_records)
    predictions_from_alias = from_alias.predict(raw_records)

    if not np.allclose(predictions_from_run, predictions_from_alias):
        raise SystemExit("FAIL: the same model predicts differently via run vs alias")

    if not np.all(predictions_from_run > 0):
        raise SystemExit("FAIL: predictions are not positive dollar amounts")

    print(f"OK: {SAMPLE_SIZE} raw records, identical predictions both ways")
    print(f"  first three: {predictions_from_run[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
