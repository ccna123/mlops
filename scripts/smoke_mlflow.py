"""Smoke test: log a run and a model to real MLflow."""

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.dummy import DummyRegressor

mlflow.set_tracking_uri("http://localhost:5000")
mlflow.set_experiment("smoke-test")

X = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
y = pd.Series([10.0, 20.0, 30.0])
model = DummyRegressor().fit(X, y)

with mlflow.start_run() as run:
    mlflow.log_param("trial", "smoke")
    mlflow.log_metric("rmse", 1.23)
    # MLflow 2.x uses `artifact_path`; the `name` param only exists from MLflow 3.
    mlflow.sklearn.log_model(model, artifact_path="model")
    print("run_id:", run.info.run_id)
    print("artifact_uri:", mlflow.get_artifact_uri())
