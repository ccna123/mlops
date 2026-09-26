"""Building a dataset version from served traffic that has ground truth (CN-42).

The build itself runs in the `feedback_data_pipeline` DAG's container: it
reads and rewrites a whole dataset version, which is not this process's memory
to spend. What happens here is cheap: count how many predictions would become
feedback records, refuse a name already taken, and start the run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ml_common.datasets import dataset_exists
from ml_common.feedback import MIN_FEEDBACK_RECORDS, default_period, matched_predictions

from ..clients.registry import MODEL_TASK_TYPES
from ..deps import require_auth
from .data import DATASET_VERSION_PATTERN

router = APIRouter()

DAG_ID = "feedback_data_pipeline"
MODEL_BY_TASK_TYPE = {task_type: name for name, task_type in MODEL_TASK_TYPES.items()}


def _period(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    """Fills in the default period for whichever end was left out.

    Args:
        start: chosen start, or None.
        end: chosen end, or None.

    Returns:
        `(start, end)`, timezone-aware.

    Raises:
        HTTPException: 422 when a time has no UTC offset, or start is not
            before end.

    Example:
        _period(None, None)  # -> the last 30 days
    """
    default_start, default_end = default_period()
    start, end = start or default_start, end or default_end
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="period times need a UTC offset")
    if start >= end:
        raise HTTPException(status_code=422, detail="period_start must be before period_end")
    return start, end


@router.get("/feedback/preview", dependencies=[Depends(require_auth)])
async def preview(
    request: Request,
    task_type: Annotated[Literal["regression", "classification"], Query()],
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> dict:
    """Counts the predictions of a period that have ground truth.

    Shown before the operator confirms, so a build that would be refused for
    too little feedback is never started (the button stays locked, 02 8.3).

    Args:
        request: the FastAPI request.
        task_type: which model's traffic.
        period_start: start of the period (ISO, with offset); default 30 days ago.
        period_end: end of the period; default now.

    Returns:
        `matched` (predictions with ground truth, one per house counted once),
        `minimum` and `enough`.

    Example:
        # GET /api/feedback/preview?task_type=regression
        # -> {"matched": 1480, "minimum": 500, "enough": true, ...}
    """
    start, end = _period(period_start, period_end)
    matched = await run_in_threadpool(
        matched_predictions, request.app.state.storage, MODEL_BY_TASK_TYPE[task_type], start, end
    )
    houses = 0
    if len(matched):
        import json

        houses = len({json.loads(raw).get("property_id") for raw in matched["raw_input"]})
    return {
        "task_type": task_type,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "matched": houses,
        "minimum": MIN_FEEDBACK_RECORDS,
        "enough": houses >= MIN_FEEDBACK_RECORDS,
    }


class FeedbackRunRequest(BaseModel):
    """What the dashboard sends to build a feedback dataset version.

    Example:
        # POST /api/feedback/run
        # {"task_type": "regression", "new_version": "v1-fb1"}
    """

    task_type: Literal["regression", "classification"]
    new_version: str = Field(pattern=DATASET_VERSION_PATTERN)
    source_version: str | None = Field(default=None, pattern=DATASET_VERSION_PATTERN)
    period_start: datetime | None = None
    period_end: datetime | None = None


@router.post("/feedback/run", dependencies=[Depends(require_auth)])
async def run(request: Request, body: FeedbackRunRequest) -> dict:
    """Starts building a feedback dataset version.

    Args:
        request: the FastAPI request.
        body: the task, the new version's name, and optionally the source
            version (default: the one the champion learned from) and period.

    Returns:
        `run_id`, `dag_id` and `state` as soon as the run is queued.

    Raises:
        HTTPException: 409 when the new name is taken (CN-02); 422 for an
            invalid name or period. The stage checks the name again, so a name
            taken in between is still refused.

    Example:
        # -> {"run_id": "manual__...", "dag_id": "feedback_data_pipeline",
        #     "state": "queued"}
    """
    start, end = _period(body.period_start, body.period_end)
    if await run_in_threadpool(dataset_exists, request.app.state.storage, body.new_version):
        raise HTTPException(
            status_code=409,
            detail=f"dataset version {body.new_version!r} already exists; choose another name",
        )
    conf = {
        "task_type": body.task_type,
        "new_version": body.new_version,
        "source_version": body.source_version or "",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }
    return request.app.state.airflow.trigger_run(DAG_ID, conf)


@router.get("/feedback/status", dependencies=[Depends(require_auth)])
def status(request: Request) -> dict:
    """Reports the most recent feedback build, with its task state.

    Args:
        request: the FastAPI request.

    Returns:
        `run` with `run_id`, `state`, timings and `tasks`, or None when no
        build ever ran (a normal first-time state, so 200 rather than 404).

    Example:
        # GET /api/feedback/status -> {"run": {"state": "success", ...}}
    """
    airflow = request.app.state.airflow
    runs = airflow.list_runs(DAG_ID, 1)
    if not runs:
        return {"run": None}
    detail = airflow.get_run(DAG_ID, runs[0]["run_id"])
    return {"run": {**runs[0], "tasks": detail["tasks"]}}
