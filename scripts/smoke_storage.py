"""Smoke test: write and read a parquet file on real MinIO."""

import os

import pandas as pd

os.environ["MINIO_ENDPOINT"] = "http://localhost:9000"
os.environ.pop("MINIO_ENDPOINT_INTERNAL", None)  # running from host, not inside a container
os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
os.environ["MINIO_SECRET_KEY"] = "minioadmin"
os.environ["ML_BUCKET"] = "ml-pipeline"

from ml_common.storage import Storage

store = Storage.from_env()
store.write_parquet(pd.DataFrame({"a": [1, 2, 3]}), "smoke-test/sample.parquet")
print(store.read_parquet("smoke-test/sample.parquet"))
print("keys:", store.list_keys("smoke-test/"))
print("exists:", store.exists("smoke-test/sample.parquet"))
