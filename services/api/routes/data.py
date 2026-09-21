"""Uploading a raw dataset and previewing what is in it.

The source CSV is hundreds of megabytes and the machine running this has
16GB of RAM and seven other containers on it. Nothing in the handler reads a
whole upload into memory: it copies the upload to a temporary file, converts
it to parquet a chunk at a time, uploads with `Storage.upload_file`, and
deletes its temporary files on every path.

The size cap bounds what this handler copies and converts, which protects RAM
and CPU and stops it writing a second CSV copy beyond the limit. It does NOT
bound what the framework receives: FastAPI parses the multipart body before
the handler or `require_auth` runs, so the whole upload has already arrived
and been spooled to disk by the time the 413 can fire. Peak disk use for one
upload is therefore up to about three copies (the framework's spooled body,
the CSV copy up to the cap, and the parquet), which matters on a nearly full
C: drive. Bounding reception itself would take a reverse proxy or middleware
and is deliberately out of scope here.

The conversion and the upload are blocking calls, so they run in a worker
thread. Only the network read stays on the event loop, which keeps `/health`
answering while a large upload is being processed.
"""

from __future__ import annotations

import os
import tempfile
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from ml_common import schema
from ml_common.rawdata import csv_to_parquet
from ml_common.storage import raw_key
from ml_common.validation import validate_dataframe

from ..deps import require_auth

router = APIRouter()

CHUNK_BYTES = 1024 * 1024

# Starts with a letter or digit so that "." and ".." cannot be versions, and
# excludes "/" so a version cannot nest. The pipeline's extract stage looks
# for exactly one `raw/<version>/data.parquet`.
DATASET_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"

MAX_PREVIEW_ROWS = 200
DEFAULT_PREVIEW_ROWS = 50

# How many leading rows the column stats are computed on. The raw dataset can
# have 2,000,000 all-string rows, several gigabytes as a DataFrame, and this
# runs on every visit to the Data page. It matches the head slice the extract
# stage takes for `sample_rows`, so the preview looks at the same kind of data
# a development run trains on.
PREVIEW_STATS_ROWS = 200_000


@router.post("/data/upload", dependencies=[Depends(require_auth)])
async def upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    dataset_version: Annotated[str, Form(pattern=DATASET_VERSION_PATTERN)],
) -> dict:
    """Streams a CSV to object storage as the raw dataset of a version.

    Uploading to a version that already exists replaces it. That is safe: the
    pipeline fingerprints the object's etag, so a replaced dataset is seen as
    new data rather than served from a stale cache.

    Args:
        request: the FastAPI request.
        file: the uploaded CSV.
        dataset_version: which version to write under, e.g. "v2". Letters,
            digits, dots, underscores and hyphens only, starting with a letter
            or digit, at most 64 characters.

    Returns:
        `dataset_version`, `rows` and `size_mb`. `size_mb` is the size of the
        parquet object that was stored, not of the CSV that was uploaded.

    Raises:
        HTTPException: 422 when the file is not a `.csv`, when the CSV cannot
            be parsed (a malformed row, bytes that are not text), or when it
            has a header but no rows; 413 when it exceeds the cap. The cap
            limits what this handler copies and converts, not what has
            already been received: the framework has spooled the whole body
            to disk before the handler starts, so a 413 arrives only after
            the full upload has (see the module docstring). A
            `dataset_version` that does not match the pattern is also a 422,
            raised by FastAPI before this runs.

    Example:
        # POST /api/data/upload  (multipart: file=..., dataset_version=v2)
        # -> {"dataset_version": "v2", "rows": 2000000, "size_mb": 118.4}
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="only .csv uploads are accepted")

    max_bytes = request.app.state.max_upload_bytes
    with tempfile.TemporaryDirectory() as workdir:
        csv_path = os.path.join(workdir, "upload.csv")
        parquet_path = os.path.join(workdir, "data.parquet")

        # The cap is enforced on this copy only. The framework has already
        # spooled the full body to disk, so this stops a second oversized CSV
        # from being written and an oversized file from being converted.
        written = 0
        with open(csv_path, "wb") as handle:
            while True:
                chunk = await file.read(CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"upload exceeds the {max_bytes} byte limit",
                    )
                handle.write(chunk)

        # Every column is read as text on purpose: this is the RAW copy, and
        # parsing belongs to the Pipeline. Letting pandas infer types here
        # would quietly repair some of the dirt the pipeline exists to handle.
        # Only the conversion is guarded: pandas' ParserError, EmptyDataError
        # and UnicodeDecodeError are all ValueErrors, and all mean "this file
        # is not a CSV we can read". A failure in the upload below is not the
        # caller's fault and must not be reported as if it were.
        try:
            row_count = await run_in_threadpool(csv_to_parquet, csv_path, parquet_path, None)
        except ValueError as error:
            raise HTTPException(
                status_code=422, detail=f"could not parse the CSV: {error}"
            ) from error
        if row_count == 0:
            raise HTTPException(status_code=422, detail="the CSV has no data rows")

        await run_in_threadpool(
            request.app.state.storage.upload_file, parquet_path, raw_key(dataset_version)
        )
        return {
            "dataset_version": dataset_version,
            "rows": row_count,
            "size_mb": round(os.path.getsize(parquet_path) / 2**20, 2),
        }


@router.get("/data/{dataset_version}/preview", dependencies=[Depends(require_auth)])
def preview(
    request: Request,
    dataset_version: Annotated[str, Path(pattern=DATASET_VERSION_PATTERN)],
    rows: int = Query(DEFAULT_PREVIEW_ROWS, gt=0),
) -> dict:
    """Shows a sample of a raw dataset and the state of each column.

    Only the first `PREVIEW_STATS_ROWS` rows of the file are read, never the
    whole dataset. The column stats therefore cover those rows only, the same
    head slice the extract stage takes for `sample_rows`. They are an estimate
    for the whole file only when the file is not ordered in a way that makes
    its start unrepresentative; nothing here shuffles it.

    Args:
        request: the FastAPI request.
        dataset_version: which version to read, e.g. "v1". Same pattern as the
            upload route: letters, digits, dots, underscores and hyphens, at
            most 64 characters, starting with a letter or digit.
        rows: how many sample rows to show. Must be greater than zero (422
            otherwise); anything above MAX_PREVIEW_ROWS is silently reduced to
            it. This is ONLY the preview size; it has nothing to do with the
            `sample_rows` that limits a training run, and the UI must not
            let the two look like the same control.

    Returns:
        `total_rows` (the exact row count of the whole file, from the parquet
        footer), `stats_rows` (how many rows the column stats were computed
        on: `min(total_rows, PREVIEW_STATS_ROWS)`, so the UI can say "stats
        from the first N of M rows"), `sample` (a list of row dicts, missing
        values as null) and `columns`, each with `name`, `kind`,
        `missing_rate` and `out_of_bounds`, sorted by name. `stats_rows` is an
        addition to the `{columns, sample, total_rows}` shape of the spec. The
        stats come from `ml_common.validation`, the same code the validate
        stage runs, so the dashboard and the pipeline cannot disagree about
        how dirty the data is.

    Raises:
        HTTPException: 404 when that dataset version has not been uploaded.
            Every other storage error propagates as a 500. A `dataset_version`
            that does not match the pattern, or `rows` that is not positive,
            is a 422 raised by FastAPI before this runs.

    Example:
        # GET /api/data/v1/preview?rows=50
        # -> {"total_rows": 2000000, "stats_rows": 200000,
        #     "sample": [{"property_id": "p1", "city": "  NEW YORK ", ...}],
        #     "columns": [{"name": "bedrooms", "kind": "numeric",
        #                  "missing_rate": 0.031, "out_of_bounds": 87}]}
    """
    try:
        head, total_rows = request.app.state.storage.read_parquet_head(
            raw_key(dataset_version), PREVIEW_STATS_ROWS
        )
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404, detail=f"no dataset at version {dataset_version}"
        ) from error

    report = validate_dataframe(head, "regression")

    # NaN is not valid JSON, and the response encoder raises on it. Turn every
    # missing value into None; astype(object) first so a float column can
    # actually hold None.
    sample_frame = head.head(min(rows, MAX_PREVIEW_ROWS)).astype(object)
    sample_frame = sample_frame.where(sample_frame.notna(), None)

    columns = [
        {
            "name": name,
            "kind": schema.COLUMNS[name].kind,
            "missing_rate": counts["missing_rate"],
            "out_of_bounds": counts["out_of_bounds"],
        }
        for name, counts in sorted(report["columns"].items())
    ]
    return {
        "total_rows": total_rows,
        "stats_rows": report["row_count"],
        "sample": sample_frame.to_dict(orient="records"),
        "columns": columns,
    }
