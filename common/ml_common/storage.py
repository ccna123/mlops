"""boto3 wrapper and the ENTIRE path convention for MinIO/S3.

This is the single place in the system that knows about object storage.
When migrating to real S3, only `endpoint_url` needs to go away — no other
file needs to change.

Never concatenate paths by hand anywhere else: use the *_key() functions
here. See the plan's Global Constraints.
"""

from __future__ import annotations

import io
import json
import os
from datetime import date

import boto3
import pandas as pd
from botocore.exceptions import ClientError

from . import schema

_SPLITS = ("train", "test")


def raw_key(dataset_version: str) -> str:
    """Path to the raw data of a dataset version."""
    return f"raw/{dataset_version}/data.parquet"


def _check_task_type(task_type: str) -> None:
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")


def processed_key(fingerprint: str, task_type: str, split: str) -> str:
    """Path to processed data, named after the raw data's fingerprint and the task.

    The fingerprint acts as a cache key: `prepare_dataset_for_train` skips work if the
    files already exist. It hashes only the raw data, so both task types share it —
    yet their processed files differ (different target, different rows dropped).
    The task type is part of the path so one task can never pick up the other's cache.
    """
    _check_task_type(task_type)
    if split not in _SPLITS:
        raise ValueError(f"split must be one of {_SPLITS}, got: {split!r}")
    return f"processed/{fingerprint}/{task_type}/{split}.parquet"


def processed_prefix(fingerprint: str, task_type: str) -> str:
    """Prefix covering both train and test for one fingerprint and task type."""
    _check_task_type(task_type)
    return f"processed/{fingerprint}/{task_type}/"


def extracted_key(fingerprint: str) -> str:
    """Path to the sampled working copy that `extract` writes.

    Separate from `raw/`: raw holds the full dataset as it arrived, while this
    holds exactly the rows this pipeline run will use, after SAMPLE_ROWS.
    """
    return f"extracted/{fingerprint}/data.parquet"


def validation_report_key(fingerprint: str) -> str:
    """Path to the counts `validate` produces for one fingerprint."""
    return f"reports/validation/{fingerprint}.json"


def baseline_key(model_name: str, version: int | str) -> str:
    """Statistical profile of the train set, tied to a specific model version."""
    return f"monitoring-baseline/{model_name}/{version}/profile.json"


def inference_log_key(model_name: str, day: date, part_id: str) -> str:
    """One inference log file, partitioned by day."""
    return f"inference-log/{model_name}/dt={day.isoformat()}/part-{part_id}.parquet"


def inference_log_prefix(model_name: str, day: date) -> str:
    """Prefix covering all inference logs for a day."""
    return f"inference-log/{model_name}/dt={day.isoformat()}/"


def ground_truth_key(model_name: str, day: date, part_id: str) -> str:
    """One ground-truth file from /feedback, partitioned by day."""
    return f"ground-truth/{model_name}/dt={day.isoformat()}/part-{part_id}.parquet"


def ground_truth_prefix(model_name: str, day: date) -> str:
    """Prefix covering all ground truth for a day."""
    return f"ground-truth/{model_name}/dt={day.isoformat()}/"


def report_key(model_name: str, run_id: str, ext: str) -> str:
    """Evidently report for one monitoring run."""
    return f"reports/{model_name}/{run_id}/evidently.{ext}"


class Storage:
    """Reads/writes parquet and json on S3-compatible object storage."""

    def __init__(
        self,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
    ):
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )

    @classmethod
    def from_env(cls) -> Storage:
        """Builds a Storage from environment variables.

        Inside a container, use MINIO_ENDPOINT_INTERNAL (http://minio:9000);
        running from the host, use MINIO_ENDPOINT (http://localhost:9000).
        """
        endpoint = os.environ.get("MINIO_ENDPOINT_INTERNAL") or os.environ["MINIO_ENDPOINT"]
        return cls(
            endpoint_url=endpoint,
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            bucket=os.environ.get("ML_BUCKET", "ml-pipeline"),
        )

    def write_parquet(self, df: pd.DataFrame, key: str) -> None:
        """Writes a DataFrame as parquet (snappy compression)."""
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False, compression="snappy")
        buffer.seek(0)
        self._client.put_object(Bucket=self.bucket, Key=key, Body=buffer.getvalue())

    def read_parquet(self, key: str) -> pd.DataFrame:
        """Reads a parquet file into a DataFrame."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return pd.read_parquet(io.BytesIO(response["Body"].read()))

    def write_json(self, obj: dict, key: str) -> None:
        """Writes a dict as UTF-8 JSON."""
        content = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
        )

    def read_json(self, key: str) -> dict:
        """Reads a JSON file into a dict."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def write_bytes(self, data: bytes, key: str, content_type: str) -> None:
        """Writes raw bytes — used for Evidently's HTML report in Plan 4."""
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def upload_file(self, local_path: str, key: str) -> None:
        """Uploads a file from disk without reading it into memory first.

        Used for seeding raw data: the source CSV is hundreds of megabytes, and
        materializing it as a DataFrame just to upload it would not fit.
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        self._client.upload_file(local_path, self.bucket, key)

    def object_etag(self, key: str) -> str:
        """ETag of an object, used as a cheap content fingerprint.

        S3 quotes the ETag in the response; the quotes are stripped so the
        value can go straight into a path or a hash.
        """
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404", "NoSuchBucket"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return response["ETag"].strip('"')

    def exists(self, key: str) -> bool:
        """True if the key exists."""
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def list_keys(self, prefix: str) -> list[str]:
        """List of keys under a prefix, with pagination."""
        result: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                result.append(obj["Key"])
        return result
