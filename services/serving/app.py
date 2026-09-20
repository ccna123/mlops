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

    Args:
        records: one batch, straight from `InferenceLogBuffer.take`. Each record
            carries `model_name` and `day`, which decide where it lands; `day`
            is dropped from the file itself, since the path already says it.

    Returns:
        Nothing. Writes one parquet object per (model, day) present in the
        batch, each under a fresh random part id so concurrent flushes never
        overwrite each other.

    Raises:
        Exception: anything object storage raises. The caller catches it and
            hands the records back to the buffer to retry.

    Example:
        write_batch([
            {"model_name": "house_price_regressor", "day": "2026-09-20", ...},
            {"model_name": "house_needs_renovation_classifier", "day": "2026-09-20", ...},
            {"model_name": "house_price_regressor", "day": "2026-09-21", ...},
        ])
        # -> 3 records, but THREE separate objects, one per (model, day) pair.
        # Grouping by the record's own `day` is what makes a batch that
        # straddles midnight still land in the right partitions.
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
    """Builds the app. Every collaborator is injectable so tests need no infra.

    Args:
        registry: where champions come from. None builds one that talks to the
            real MLflow Registry.
        buffer: where prediction records wait. None builds one with the default
            size and age triggers.
        flush: what writes a batch. Takes a list of records and returns nothing;
            tests pass a function that appends to a list.
        start_flusher: False skips the background flush loop, so a test can
            drive `drain` itself instead of waiting on real time.

    Returns:
        A FastAPI app serving GET /health, POST /reload and
        POST /predict/{task_type}. Champions are loaded on startup, and any
        partial batch is flushed on shutdown.

    Example:
        # Production — module level, everything real:
        app = create_app()

        # A test — no MLflow, no MinIO, no background timer:
        written = []
        app = create_app(
            registry=ModelRegistry(loader=lambda name: (FakeModel(), "1")),
            buffer=InferenceLogBuffer(flush_size=2),
            flush=written.append,
            start_flusher=False,
        )
        client = TestClient(app)
        client.post("/predict/regression", json={"list_price": "$450,000"})
    """
    registry = registry if registry is not None else ModelRegistry()
    buffer = buffer if buffer is not None else InferenceLogBuffer()

    def drain(force: bool = False) -> None:
        """Hands one batch to the writer, putting it back if the write fails.

        Args:
            force: True skips the size-or-age check. Shutdown uses it: a partial
                batch still waiting for its 30 seconds would otherwise die with
                the container.

        Returns:
            Nothing, and never raises. A failed write is logged to stderr and
            its records go back to the buffer for the next attempt.

        Example:
            drain()       # every second from the flusher; a no-op when not ready
            drain(True)   # at shutdown, taking whatever is there
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
        """Polls the buffer forever, draining it whenever it is ready.

        Args:
            None.

        Returns:
            Never returns on its own; lifespan cancels it at shutdown. `drain`
            runs in a worker thread so its blocking write cannot stall the
            event loop that is answering requests.
        """
        while True:
            await asyncio.sleep(FLUSH_POLL_SECONDS)
            await asyncio.to_thread(drain)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Loads the champions on startup and drains the buffer on shutdown.

        Args:
            _: the app, which FastAPI passes and nothing here needs.

        Yields:
            Once, while the app serves traffic. Before the yield the champions
            are loaded and the flusher starts; after it the flusher is
            cancelled and one last forced drain runs, so a partial batch is not
            lost with the container.
        """
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
        """Reports what is loaded and how the inference log is doing.

        Args:
            None.

        Returns:
            `status`, "ok" when at least one champion is loaded and "degraded"
            when none is; `models`, the per-task block from
            `ModelRegistry.describe`; and `inference_log`, the buffer's
            buffered and dropped counts. Always HTTP 200 — "degraded" is a
            state to read, not a request that failed.

        Example:
            # curl http://localhost:8000/health
            # {"status": "degraded",
            #  "models": {
            #    "regression":     {"loaded": true,  "name": "house_price_regressor",
            #                       "version": "3"},
            #    "classification": {"loaded": false, "name": "house_needs_renovation_...",
            #                       "version": null}},
            #  "inference_log": {"buffered": 137, "dropped": 0}}
            #
            # "degraded" here means the classifier has never been trained —
            # regression predictions are being served normally.
        """
        described = registry.describe()
        any_loaded = any(entry["loaded"] for entry in described.values())
        return {
            "status": "ok" if any_loaded else "degraded",
            "models": described,
            "inference_log": buffer.stats(),
        }

    @app.post("/reload")
    def reload() -> dict:
        """Re-reads the champion of every task from the Registry.

        Called by the DAG's deploy task right after `register` moves an alias,
        which is what makes a freshly promoted model reachable without a
        restart.

        Args:
            None.

        Returns:
            `models`, the same block /health returns, so the caller can see
            which versions are live now. A model that failed to load leaves
            that task unloaded and is not an error.

        Example:
            # curl -X POST http://localhost:8000/reload
            # {"models": {"regression": {"loaded": true, ..., "version": "4"}, ...}}
            #
            # The DAG's deploy task is the usual caller, right after register
            # moves the alias. Call it by hand after promoting a model outside
            # the DAG — otherwise serving keeps the version it started with.
        """
        registry.reload()
        return {"models": registry.describe()}

    @app.post("/predict/{task_type}")
    def predict(
        task_type: Literal["regression", "classification"],
        record: Annotated[dict, Body()],
    ) -> dict:
        """Predicts for one RAW record and logs the call for monitoring.

        Args:
            task_type: "regression" or "classification", from the path. FastAPI
                rejects anything else with a 422 before this runs.
            record: one house as a JSON object, exactly as it comes — money may
                still read "$450,000", city may still read "  NEW YORK ". The
                model carries its own cleaning; do not clean here.

        Returns:
            `request_id`, `prediction` (dollars for regression, a bool for
            classification), `model_name` and `model_version`, plus
            `probability` when the classifier exposes one.

        Raises:
            HTTPException: 503 when no champion is loaded for that task — train
                it, then POST /reload. 500 when the model itself fails on the
                record, with the reason in the detail.

        Example:
            # POST /predict/regression
            # {
            #   "list_price": "$450,000",
            #   "city": "  NEW YORK ",
            #   "listing_date": "09/20/2026",
            #   "bedrooms": 3, "has_pool": "Yes"
            # }
            # {"request_id": "3f0a-...", "prediction": 487312.5,
            #  "model_name": "house_price_regressor", "model_version": "3"}
            #
            # Note what was NOT done to that payload: no currency stripping, no
            # lowercasing, no date parsing. The Pipeline inside the model does
            # all of it, with the exact code that ran at training time.

            # Classification also returns a probability:
            # POST /predict/classification
            # -> {"prediction": true, "probability": 0.83, ...}
        """
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
