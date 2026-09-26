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
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from . import schema

_SPLITS = ("train", "test")
_DRIFT_SUMMARY_NAME = "summary.json"


def raw_key(dataset_version: str) -> str:
    """Builds the path to the raw data of a dataset version.

    Args:
        dataset_version: the version label, e.g. "v1".

    Returns:
        The key, e.g. "raw/v1/data.parquet". Nothing is checked against
        storage: the key exists as a name whether or not an object is there.

    Example:
        raw_key("v1")  # -> "raw/v1/data.parquet"

        # Always build keys this way, never by hand. When this moves to real
        # S3, this file is the only one that changes.
        etag = storage.object_etag(raw_key("v1"))
    """
    return f"raw/{dataset_version}/data.parquet"


def dataset_manifest_key(dataset_version: str) -> str:
    """Builds the path to the manifest of a dataset version.

    The manifest sits next to the raw data and holds what was decided once,
    when the version was created: its split points and where it came from.

    Args:
        dataset_version: the version label, e.g. "v1".

    Returns:
        The key, e.g. "raw/v1/manifest.json".

    Example:
        dataset_manifest_key("v2")  # -> "raw/v2/manifest.json"
    """
    return f"raw/{dataset_version}/manifest.json"


def _check_task_type(task_type: str) -> None:
    """Rejects a task type the schema does not know.

    Args:
        task_type: the value to check.

    Returns:
        Nothing when the value is valid.

    Raises:
        ValueError: otherwise. A typo must not silently become a new prefix
            that no other stage will ever look under.

    Example:
        _check_task_type("regression")  # -> None, carry on
        _check_task_type("regresion")   # -> ValueError
        # Without this, the typo would build "processed/<fp>/regresion/" and
        # the train stage would report a missing file instead of a typo.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")


def processed_key(fingerprint: str, task_type: str, split: str) -> str:
    """Builds the path to processed data for one fingerprint, task and split.

    The fingerprint acts as a cache key: `prepare_dataset_for_train` skips work if the
    files already exist. It hashes only the raw data, so both task types share it —
    yet their processed files differ (different target, different rows dropped).
    The task type is part of the path so one task can never pick up the other's cache.

    Args:
        fingerprint: the value `fingerprint.compute_fingerprint` produced.
        task_type: "regression" or "classification".
        split: "train" or "test".

    Returns:
        The key, e.g. "processed/ab12cd34.../regression/train.parquet".

    Raises:
        ValueError: when task_type or split is not one of the allowed values.

    Example:
        processed_key("3f0a9c1d5e2b7a48", "regression", "train")
        # -> "processed/3f0a9c1d5e2b7a48/regression/train.parquet"

        processed_key("3f0a9c1d5e2b7a48", "classification", "train")
        # -> a DIFFERENT path, same fingerprint. Both tasks read the same raw
        #    data but drop different rows and build a different target, so
        #    sharing one cache entry would train on the wrong split.
    """
    _check_task_type(task_type)
    if split not in _SPLITS:
        raise ValueError(f"split must be one of {_SPLITS}, got: {split!r}")
    return f"processed/{fingerprint}/{task_type}/{split}.parquet"


def processed_prefix(fingerprint: str, task_type: str) -> str:
    """Builds the prefix covering both splits of one fingerprint and task type.

    Args:
        fingerprint: the value `fingerprint.compute_fingerprint` produced.
        task_type: "regression" or "classification".

    Returns:
        The prefix, trailing slash included so `list_keys` cannot match a
        sibling whose name merely starts the same way.

    Example:
        processed_prefix("3f0a9c1d5e2b7a48", "regression")
        # -> "processed/3f0a9c1d5e2b7a48/regression/"
        storage.list_keys(processed_prefix(fp, "regression"))
        # -> [".../train.parquet", ".../test.parquet"]

    Raises:
        ValueError: when task_type is not one of `schema.TASK_TYPES`.
    """
    _check_task_type(task_type)
    return f"processed/{fingerprint}/{task_type}/"


def extracted_key(fingerprint: str) -> str:
    """Builds the path to the sampled working copy that `extract` writes.

    Separate from `raw/`: raw holds the full dataset as it arrived, while this
    holds exactly the rows this pipeline run will use, after SAMPLE_ROWS.

    Args:
        fingerprint: the value `fingerprint.compute_fingerprint` produced.

    Returns:
        The key, e.g. "extracted/ab12cd34.../data.parquet".

    Example:
        extracted_key("3f0a9c1d5e2b7a48")
        # -> "extracted/3f0a9c1d5e2b7a48/data.parquet"

        # raw/ holds 2 million rows as they arrived; this holds the 200k this
        # run will actually use. Every stage after extract reads from here.
    """
    return f"extracted/{fingerprint}/data.parquet"


def validation_report_key(fingerprint: str) -> str:
    """Builds the path to the counts `validate` produces for one fingerprint.

    Args:
        fingerprint: the value `fingerprint.compute_fingerprint` produced.

    Returns:
        The key, e.g. "reports/validation/ab12cd34....json".

    Example:
        validation_report_key("3f0a9c1d5e2b7a48")
        # -> "reports/validation/3f0a9c1d5e2b7a48.json"
        # Keyed by fingerprint, not by task: the counts describe the raw data,
        # which both tasks share.
    """
    return f"reports/validation/{fingerprint}.json"


def baseline_key(model_name: str, version: int | str) -> str:
    """Builds the path to the train-set profile of one model version.

    Args:
        model_name: the registered model name, e.g. "house_price_regressor".
        version: the registry version, as an int or the string of one.

    Returns:
        The key, e.g. "monitoring-baseline/house_price_regressor/3/profile.json".
        The version is part of the path so a baseline always belongs to the
        exact model that learned from it.

    Example:
        baseline_key("house_price_regressor", 3)
        # -> "monitoring-baseline/house_price_regressor/3/profile.json"

        # Version 4 gets its own file. Overwriting one shared baseline would
        # leave Plan 4 comparing today's traffic against a distribution the
        # live model never saw.
    """
    return f"monitoring-baseline/{model_name}/{version}/profile.json"


def inference_log_key(model_name: str, day: date, part_id: str) -> str:
    """Builds the path to one inference log file, partitioned by day.

    Args:
        model_name: the registered model that served the predictions.
        day: the day the predictions were served, not the day of the flush.
        part_id: a value unique within the day; serving uses 8 hex characters.

    Returns:
        The key, e.g. "inference-log/<model>/dt=2026-09-20/part-1a2b3c4d.parquet".

    Example:
        inference_log_key("house_price_regressor", date(2026, 9, 20), uuid4().hex[:8])
        # -> "inference-log/house_price_regressor/dt=2026-09-20/part-1a2b3c4d.parquet"

        # dt= is the Hive partition convention, so the monitoring DAG can read
        # one day without opening every file ever written.
    """
    return f"inference-log/{model_name}/dt={day.isoformat()}/part-{part_id}.parquet"


def inference_log_prefix(model_name: str, day: date) -> str:
    """Builds the prefix covering every inference log of one day.

    Args:
        model_name: the registered model that served the predictions.
        day: the day to cover.

    Returns:
        The prefix, trailing slash included, for the monitoring DAG to list.

    Example:
        keys = storage.list_keys(inference_log_prefix(model_name, date(2026, 9, 20)))
        frame = pd.concat([storage.read_parquet(k) for k in keys])
        # -> every prediction served that day, however many flushes wrote it
    """
    return f"inference-log/{model_name}/dt={day.isoformat()}/"


def ground_truth_key(model_name: str, day: date, part_id: str) -> str:
    """Builds the path to one ground-truth file from /feedback.

    Args:
        model_name: the registered model the outcomes belong to.
        day: the day being reported on.
        part_id: a value unique within the day.

    Returns:
        The key, e.g. "ground-truth/<model>/dt=2026-09-20/part-1a2b3c4d.parquet".

    Example:
        ground_truth_key("house_price_regressor", date(2026, 9, 20), "1a2b3c4d")
        # -> "ground-truth/house_price_regressor/dt=2026-09-20/part-1a2b3c4d.parquet"

        # Partitioned by the day of the PREDICTION, not of the feedback, so it
        # lines up with inference-log/ when Plan 4 joins the two on request_id.
    """
    return f"ground-truth/{model_name}/dt={day.isoformat()}/part-{part_id}.parquet"


def ground_truth_prefix(model_name: str, day: date) -> str:
    """Builds the prefix covering every ground-truth file of one day.

    Args:
        model_name: the registered model the outcomes belong to.
        day: the day to cover.

    Returns:
        The prefix, trailing slash included.

    Example:
        # Plan 4 reads one day from each side and joins them on request_id:
        truth = storage.list_keys(ground_truth_prefix(model_name, day))
        preds = storage.list_keys(inference_log_prefix(model_name, day))
    """
    return f"ground-truth/{model_name}/dt={day.isoformat()}/"


def report_key(model_name: str, run_id: str, ext: str) -> str:
    """Builds the path to the Evidently report of one monitoring run.

    Args:
        model_name: the registered model the run monitored.
        run_id: the monitoring run's identifier.
        ext: the file extension without a dot, "html" or "json".

    Returns:
        The key, e.g. "reports/<model>/<run_id>/evidently.html".

    Example:
        report_key("house_price_regressor", "a1b2c3", "html")
        # -> "reports/house_price_regressor/a1b2c3/evidently.html"
        storage.write_bytes(html.encode("utf-8"), key, "text/html")
    """
    return f"reports/{model_name}/{run_id}/evidently.{ext}"


def drift_summary_key(model_name: str, run_id: str) -> str:
    """Builds the path to the short drift verdict of one monitoring run.

    Args:
        model_name: the registered model that was monitored.
        run_id: the monitoring run's identifier.

    Returns:
        The key, e.g. "reports/house_price_regressor/a1b2c3/summary.json".
        It sits in the same prefix as the full Evidently report, so one
        listing finds both, but it stays small enough to read in bulk when
        drawing a history.

    Example:
        drift_summary_key("house_price_regressor", "a1b2c3")
        # -> "reports/house_price_regressor/a1b2c3/summary.json"
    """
    return f"reports/{model_name}/{run_id}/{_DRIFT_SUMMARY_NAME}"


def drift_latest_key(model_name: str) -> str:
    """Builds the path to the most recent drift verdict for a model.

    Args:
        model_name: the registered model.

    Returns:
        The key, e.g. "reports/house_price_regressor/latest.json". One object
        per model, overwritten every run.

    Example:
        drift_latest_key("house_price_regressor")
        # -> "reports/house_price_regressor/latest.json"

        # Plan 5 answers /api/drift/latest with a single read of this key,
        # rather than listing the whole prefix and comparing timestamps.
    """
    return f"reports/{model_name}/latest.json"


def drift_prefix(model_name: str) -> str:
    """Builds the prefix holding every drift object of one model.

    Args:
        model_name: the registered model.

    Returns:
        The prefix, trailing slash included so `list_keys` cannot match a
        model whose name merely starts the same way. It covers everything
        `drift_summary_key`, `drift_latest_key` and `report_key` produce, so
        a listing returns all three kinds mixed together - filter the result
        with `is_drift_summary_key` when only the summaries are wanted.

    Example:
        drift_prefix("house_price_regressor")
        # -> "reports/house_price_regressor/"
        storage.list_keys(drift_prefix("house_price_regressor"))
        # -> [".../20260920T0700/evidently.html",
        #     ".../20260920T0700/summary.json",
        #     ".../latest.json"]
    """
    return f"reports/{model_name}/"


def is_drift_summary_key(key: str) -> bool:
    """Tells whether a key is the per-run drift summary of some monitoring run.

    Args:
        key: a full key, typically one item of `list_keys(drift_prefix(...))`.

    Returns:
        True only for the shape `drift_summary_key` builds. False for
        `latest.json` (a copy of one summary, so counting it would show the
        newest run twice), for Evidently's html and json (not summaries at
        all), and for anything outside the reports tree.

    Example:
        is_drift_summary_key(drift_summary_key("house_price_regressor", "a1b2c3"))
        # -> True
        is_drift_summary_key(drift_latest_key("house_price_regressor"))
        # -> False
        is_drift_summary_key(report_key("house_price_regressor", "a1b2c3", "json"))
        # -> False
    """
    parts = key.split("/")
    return len(parts) == 4 and parts[0] == "reports" and parts[3] == _DRIFT_SUMMARY_NAME


class Storage:
    """Reads/writes parquet and json on S3-compatible object storage.

    Example:
        # Everywhere in the pipeline, built from the environment:
        storage = Storage.from_env()
        df = storage.read_parquet(extracted_key(fingerprint))
        storage.write_parquet(train_df, processed_key(fingerprint, task, "train"))
        storage.write_json(report, validation_report_key(fingerprint))

        # In tests, built by hand against moto:
        storage = Storage(None, "key", "secret", "test-bucket")
    """

    def __init__(
        self,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
    ):
        """Opens a client against one bucket.

        Args:
            endpoint_url: where the S3 API lives. None targets real AWS S3;
                a URL targets MinIO. This is the ONLY thing that changes when
                migrating off MinIO.
            access_key: the access key id.
            secret_key: the secret access key.
            bucket: the bucket every key in this instance is relative to.
        """
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

        Args:
            None. Reads MINIO_ENDPOINT_INTERNAL or MINIO_ENDPOINT,
            MINIO_ACCESS_KEY, MINIO_SECRET_KEY, and ML_BUCKET (default
            "ml-pipeline").

        Returns:
            A ready Storage.

        Raises:
            KeyError: when a required variable is unset. Failing at startup
                beats failing halfway through a stage that already wrote data.

        Example:
            # Inside a container — MINIO_ENDPOINT_INTERNAL is set, and wins:
            storage = Storage.from_env()        # -> talks to http://minio:9000

            # From the host, a smoke script clears the internal name first:
            os.environ.pop("MINIO_ENDPOINT_INTERNAL", None)
            os.environ["MINIO_ENDPOINT"] = "http://localhost:9000"
            storage = Storage.from_env()
        """
        endpoint = os.environ.get("MINIO_ENDPOINT_INTERNAL") or os.environ["MINIO_ENDPOINT"]
        return cls(
            endpoint_url=endpoint,
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            bucket=os.environ.get("ML_BUCKET", "ml-pipeline"),
        )

    def write_parquet(self, df: pd.DataFrame, key: str) -> None:
        """Writes a DataFrame as parquet (snappy compression).

        Args:
            df: the frame to write. Its index is not written — a positional
                index carries no meaning and would come back as a column.
            key: the destination key, built by one of the *_key() functions.

        Returns:
            Nothing. An existing object at that key is overwritten.

        Example:
            storage.write_parquet(train_df, processed_key(fp, "regression", "train"))
            # Overwrites silently if the key exists — which is why the prepare
            # stage checks exists() first and skips on a cache hit.
        """
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False, compression="snappy")
        buffer.seek(0)
        self._client.put_object(Bucket=self.bucket, Key=key, Body=buffer.getvalue())

    def _get_object_bytes(self, key: str) -> bytes:
        """Downloads one whole object into memory.

        Args:
            key: the key to read, built by one of the *_key() functions.

        Returns:
            The object's bytes.

        Raises:
            FileNotFoundError: when the key does not exist. Any other S3 error
                (credentials, network) propagates as it is: a missing object is
                an ordinary outcome, a broken connection is not.

        Example:
            data = self._get_object_bytes(raw_key("v1"))
            len(data)     # -> 124000000
        """
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return response["Body"].read()

    def read_parquet(self, key: str, columns: list[str] | None = None) -> pd.DataFrame:
        """Reads a parquet file into a DataFrame.

        Args:
            key: the key to read, built by one of the *_key() functions.
            columns: decode only these columns, or None for all. The whole
                object is still downloaded; only the decoding is bounded,
                which is what costs RAM on a 2-million-row string dataset.

        Returns:
            The frame, with a fresh positional index.

        Raises:
            FileNotFoundError: when the key does not exist. Any other S3 error
                (credentials, network) propagates as it is: a missing object is
                an ordinary outcome, a broken connection is not.

        Example:
            df = storage.read_parquet(extracted_key(fingerprint))

            try:
                df = storage.read_parquet(processed_key(fp, task, "train"))
            except FileNotFoundError:
                ...  # prepare has not run for this fingerprint yet
        """
        return pd.read_parquet(io.BytesIO(self._get_object_bytes(key)), columns=columns)

    def read_parquet_head(self, key: str, rows: int) -> tuple[pd.DataFrame, int]:
        """Reads the first rows of a parquet file, plus how many rows it has in total.

        Use this instead of `read_parquet` when only a sample is needed: the
        full frame of a 2,000,000-row all-string raw dataset takes several
        gigabytes of RAM, while the head takes a few megabytes. The total row
        count comes free from the parquet footer.

        The compressed object is still downloaded into memory once (about
        120 MB for the raw dataset), because a true ranged read would need
        s3fs, which this project does not depend on. Only the decoding into a
        DataFrame is bounded.

        Args:
            key: the key to read, built by one of the *_key() functions.
            rows: how many leading rows to return. Must be at least 1.

        Returns:
            A tuple `(head, total_rows)`. `head` has at most `rows` rows, fewer
            when the file is smaller, and a fresh positional index. `total_rows`
            is the file's exact row count. A file with no rows returns an empty
            frame that still has the file's columns, and a total of 0.

        Raises:
            ValueError: when `rows` is less than 1.
            FileNotFoundError: when the key does not exist. Any other S3 error
                (credentials, network) propagates as it is.

        Example:
            head, total = storage.read_parquet_head(raw_key("v1"), 200_000)
            len(head)     # -> 200000
            total         # -> 2000000
        """
        if rows < 1:
            raise ValueError(f"rows must be at least 1, got: {rows}")
        parquet_file = pq.ParquetFile(io.BytesIO(self._get_object_bytes(key)))
        total_rows = parquet_file.metadata.num_rows
        first_batch = next(parquet_file.iter_batches(batch_size=rows), None)
        if first_batch is None:
            return parquet_file.schema_arrow.empty_table().to_pandas(), 0
        return first_batch.to_pandas(), total_rows

    def write_json(self, obj: dict, key: str) -> None:
        """Writes a dict as UTF-8 JSON.

        Args:
            obj: the dict to write. Anything json cannot encode by itself —
                a date, a numpy scalar — is written as its str(), so the file
                never fails to be produced.
            key: the destination key.

        Returns:
            Nothing. The object is stored with content type application/json
            so the MinIO console renders it instead of offering a download.

        Example:
            storage.write_json(report, validation_report_key(fingerprint))

            # `default=str` means a date or a numpy float does not blow up the
            # write — it is stored as its string form rather than failing:
            storage.write_json({"computed_at": date(2026, 9, 20)}, key)
            # -> {"computed_at": "2026-09-20"}
        """
        content = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
        )

    def read_json(self, key: str) -> dict:
        """Reads a JSON file into a dict.

        Args:
            key: the key to read.

        Returns:
            The decoded dict.

        Raises:
            FileNotFoundError: when the key does not exist.

        Example:
            report = storage.read_json(validation_report_key(fingerprint))
            report["row_count"]       # -> 200000
            report["columns"]["bedrooms"]["out_of_bounds"]   # -> 87
        """
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def write_bytes(self, data: bytes, key: str, content_type: str) -> None:
        """Writes raw bytes — used for Evidently's HTML report in Plan 4.

        Args:
            data: the bytes to store, already encoded.
            key: the destination key.
            content_type: the MIME type, e.g. "text/html". Passed explicitly
                because nothing here can infer it from the bytes.

        Returns:
            Nothing.

        Example:
            html = evidently_report.get_html()
            storage.write_bytes(html.encode("utf-8"),
                                report_key(model_name, run_id, "html"),
                                "text/html")
            # The content type is what makes the MinIO console render the
            # report in the browser instead of downloading it.
        """
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def read_bytes(self, key: str) -> bytes:
        """Reads one whole object back as raw bytes.

        The counterpart of `write_bytes`, added so the API can serve
        Evidently's HTML report to the dashboard without the browser ever
        talking to MinIO. Nothing is decoded: the report is UTF-8 HTML with
        embedded JavaScript, and re-encoding it on the way through would
        corrupt it.

        Args:
            key: the key to read, built by one of the *_key() functions.

        Returns:
            The object's bytes.

        Raises:
            FileNotFoundError: when the key does not exist. Every other S3
                error propagates, so a missing report and an unreachable
                MinIO stay distinguishable - the route answers 404 for the
                first and 500 for the second.

        Example:
            html = storage.read_bytes(report_key(model_name, run_id, "html"))
            # -> b"<html>..."
        """
        return self._get_object_bytes(key)

    def upload_file(self, local_path: str, key: str) -> None:
        """Uploads a file from disk without reading it into memory first.

        Used for seeding raw data: the source CSV is hundreds of megabytes, and
        materializing it as a DataFrame just to upload it would not fit.

        Args:
            local_path: the file on disk. boto3 splits it into a multipart
                upload on its own.
            key: the destination key.

        Returns:
            Nothing.

        Raises:
            FileNotFoundError: when local_path is not a file. Checked here so
                the message names the path instead of surfacing from boto3.

        Example:
            # How seed_raw_data.py delivers the raw dataset:
            storage.upload_file("/tmp/data.parquet", raw_key("v1"))

            # Use this, not write_parquet, when the file is large: a 373 MB
            # source would have to become a DataFrame in memory first.
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        self._client.upload_file(local_path, self.bucket, key)

    def object_etag(self, key: str) -> str:
        """Reads an object's ETag, used as a cheap content fingerprint.

        Args:
            key: the key to inspect. Only its metadata is fetched, so this
                costs the same whether the object is 1 KB or 400 MB.

        Returns:
            The ETag without the quotes S3 wraps it in, so the value can go
            straight into a path or a hash.

        Raises:
            FileNotFoundError: when the key, or the bucket, does not exist.

        Example:
            etag = storage.object_etag(raw_key("v1"))   # -> "9b2cf5e1a4..."
            fingerprint = compute_fingerprint("v1", etag, sample_rows)

            # The ETag stands in for hashing the file: it already changes
            # whenever the object does, so 2 million rows are never re-read
            # just to find out whether they are the same 2 million rows.
        """
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404", "NoSuchBucket"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return response["ETag"].strip('"')

    def exists(self, key: str) -> bool:
        """Checks whether a key holds an object.

        Args:
            key: the key to check.

        Returns:
            True when the object is there. Any error means False, including a
            credentials failure — callers use this to decide whether to reuse a
            cache, and the answer to "can I reuse it" is no either way.

        Example:
            # The cache check at the top of the prepare stage:
            if storage.exists(train_key) and storage.exists(test_key) and not force:
                ...  # skip the work, the split is already there
        """
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def check_reachable(self) -> None:
        """Checks that the bucket answers, as a health probe.

        One `head_bucket` request, whatever the bucket holds - it lists no keys
        and reads no object, so a caller can poll it. It says nothing when it
        succeeds and RAISES when it does not, unlike `exists`, which turns every
        error into False: a probe built on `exists` would read an outage or a
        wrong credential as "healthy, the key just is not there".

        Args:
            None.

        Returns:
            None. Reaching the end of the call is the answer.

        Raises:
            botocore.exceptions.ClientError: when storage answers but refuses -
                the bucket does not exist, or the credentials are wrong.
            botocore.exceptions.BotoCoreError: when storage cannot be reached
                at all (connection refused, timeout).

        Example:
            storage.check_reachable()   # -> None, the bucket is there
            storage.check_reachable()   # -> raises ClientError (404), no such bucket

            # A health route wraps it and turns the exception into "down":
            try:
                storage.check_reachable()
                state = "ok"
            except Exception:
                state = "down"
        """
        self._client.head_bucket(Bucket=self.bucket)

    def list_keys(self, prefix: str) -> list[str]:
        """Lists every key under a prefix.

        Args:
            prefix: the prefix to list, built by one of the *_prefix() functions.

        Returns:
            The full keys, in the order storage returns them. Pages are followed
            to the end, so a prefix holding more than 1000 objects is not
            silently truncated. An empty prefix returns an empty list.

        Example:
            storage.list_keys(inference_log_prefix(model_name, day))
            # -> ["inference-log/<model>/dt=2026-09-20/part-1a2b3c4d.parquet",
            #     "inference-log/<model>/dt=2026-09-20/part-9f8e7d6c.parquet"]

            # A busy day easily exceeds the 1000-key page limit, which is why
            # this paginates rather than calling list_objects_v2 once.
        """
        result: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                result.append(obj["Key"])
        return result
