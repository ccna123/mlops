"""Uploading a raw dataset and previewing what is in it.

The source CSV is hundreds of megabytes and the machine running this has
16GB of RAM and seven other containers on it. Nothing here reads a whole
upload into memory: it streams to a temporary file, converts it to parquet
a chunk at a time, uploads with `Storage.upload_file`, and deletes the
temporary files on every path.

The conversion and the upload are blocking calls, so they run in a worker
thread. Only the network read stays on the event loop, which keeps `/health`
answering while a large upload is being processed.
"""

from __future__ import annotations

import os
import tempfile
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from ml_common.rawdata import csv_to_parquet
from ml_common.storage import raw_key

from ..deps import require_auth

router = APIRouter()

CHUNK_BYTES = 1024 * 1024

# Starts with a letter or digit so that "." and ".." cannot be versions, and
# excludes "/" so a version cannot nest. The pipeline's extract stage looks
# for exactly one `raw/<version>/data.parquet`.
DATASET_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


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
            exists because this machine has 16GB of RAM and an out-of-memory
            kill takes the whole stack with it, which is a far worse outcome
            than a refused upload. A `dataset_version` that does not match
            the pattern is also a 422, raised by FastAPI before this runs.

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
