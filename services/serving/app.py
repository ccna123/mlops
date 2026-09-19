"""HTTP surface for model serving.

Two rules shape everything here:

The model cleans its own input. /predict takes a raw record — money still
written "$450,000", city still "  NEW YORK " — and hands it to the Pipeline
unchanged. This module must never import the cleaning module of ml_common, and
must never import its rowops module: a row-dropping transformer handed one
record returns an empty frame and takes serving down with it. (The names are
spelled out this way so the boundary check in verify_serving.ps1, which greps
for the dotted module paths, only ever matches a real import.)

Logging never blocks serving. /predict appends to an in-memory buffer and
returns; a background loop writes batches to object storage. A failure there
is logged and retried, never surfaced to the caller.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import uuid4

import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from ml_common.inference_log import InferenceLogBuffer
from ml_common.storage import Storage, inference_log_key

from .model_registry import ModelRegistry

FLUSH_POLL_SECONDS = 1.0


def write_batch(records: list[dict]) -> None:
    """Writes one batch to object storage, one file per model and per day.

    A batch can hold records for both models and can straddle midnight, while
    the key is partitioned by model and by day — so group before writing, using
    the day each record was served, not the day the flush happens.
    """
    storage = Storage.from_env()
    frame = pd.DataFrame(records)
    for (model_name, day), group in frame.groupby(["model_name", "day"], sort=False):
        key = inference_log_key(model_name, date.fromisoformat(day), uuid4().hex[:8])
        storage.write_parquet(group.drop(columns=["day"]).reset_index(drop=True), key)


def create_app(
    registry: ModelRegistry | None = None,
    buffer: InferenceLogBuffer | None = None,
    flush=write_batch,
    start_flusher: bool = True,
) -> FastAPI:
    """Builds the app. Every collaborator is injectable so tests need no infra."""
    registry = registry if registry is not None else ModelRegistry()
    buffer = buffer if buffer is not None else InferenceLogBuffer()

    def drain(force: bool = False) -> None:
        """Hands one batch to the writer, putting it back if the write fails.

        `force` skips the size-or-age check. Shutdown uses it: a partial batch
        still waiting for its 30 seconds would otherwise die with the container.
        """
        if not force and not buffer.should_flush():
            return
        records = buffer.take()
        if not records:
            return
        try:
            flush(records)
        except Exception as err:  # noqa: BLE001 - any write failure is retryable
            print(
                f"inference log flush failed, keeping {len(records)} records: {err}",
                file=sys.stderr,
            )
            buffer.give_back(records)

    async def flusher() -> None:
        while True:
            await asyncio.sleep(FLUSH_POLL_SECONDS)
            await asyncio.to_thread(drain)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        registry.reload()
        task = asyncio.create_task(flusher()) if start_flusher else None
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await asyncio.to_thread(drain, True)

    app = FastAPI(title="house pricing serving", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        described = registry.describe()
        any_loaded = any(entry["loaded"] for entry in described.values())
        return {
            "status": "ok" if any_loaded else "degraded",
            "models": described,
            "inference_log": buffer.stats(),
        }

    @app.post("/reload")
    def reload() -> dict:
        registry.reload()
        return {"models": registry.describe()}

    @app.post("/predict/{task_type}")
    def predict(
        task_type: Literal["regression", "classification"],
        record: Annotated[dict, Body()],
    ) -> dict:
        loaded = registry.get(task_type)
        if loaded is None:
            raise HTTPException(
                status_code=503,
                detail=f"no champion loaded for {task_type}; train it, then POST /reload",
            )

        frame = pd.DataFrame([record])
        try:
            prediction = loaded.model.predict(frame)[0]
            probability = None
            if task_type == "classification" and hasattr(loaded.model, "predict_proba"):
                probability = float(loaded.model.predict_proba(frame)[0][1])
        except Exception as err:  # noqa: BLE001 - surfaces as 500 with the reason
            raise HTTPException(status_code=500, detail=f"prediction failed: {err}") from err

        prediction = bool(prediction) if task_type == "classification" else float(prediction)
        now = datetime.now(UTC)
        request_id = str(uuid4())

        buffer.add(
            {
                "request_id": request_id,
                "timestamp": now.isoformat(),
                "day": now.date().isoformat(),
                "raw_input": json.dumps(record, default=str),
                "prediction": prediction,
                "model_name": loaded.name,
                "model_version": loaded.version,
            }
        )

        body = {
            "request_id": request_id,
            "prediction": prediction,
            "model_name": loaded.name,
            "model_version": loaded.version,
        }
        if probability is not None:
            body["probability"] = probability
        return body

    return app


app = create_app()
