"""Starting pipeline runs and reporting what they are doing.

A run takes minutes, so every endpoint here is a snapshot: trigger returns
as soon as Airflow has queued the run, and the dashboard polls for the rest.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..deps import require_auth

router = APIRouter()

DAG_ID = "ml_pipeline"
DEFAULT_RUN_LIMIT = 20


class RunRequest(BaseModel):
    """What the dashboard sends to start a pipeline run.

    Example:
        # POST /api/pipeline/run
        # {"task_type": "regression", "force_reprocess": false,
        #  "sample_rows": 1000, "dataset_version": "v1"}
    """

    task_type: Literal["regression", "classification"]
    force_reprocess: bool = False
    sample_rows: int | None = Field(default=None, gt=0)
    dataset_version: str = "v1"


@router.post("/pipeline/run", dependencies=[Depends(require_auth)])
def trigger_run(request: Request, body: RunRequest) -> dict:
    """Queues a pipeline run with the settings the dashboard chose.

    Args:
        request: the FastAPI request, used to reach the injected client.
        body: the run settings. `sample_rows` None means every row; a value
            of 0 or less is rejected rather than silently treated as "all",
            which would start a two-million-row run on a machine that asked
            for a small one.

    Returns:
        `run_id`, `dag_id` and `state`. The run is only QUEUED - it has not
        finished, and it will take minutes.

    Example:
        # -> {"run_id": "manual__2026-09-20T10:00:00+00:00",
        #     "dag_id": "ml_pipeline", "state": "queued"}
    """
    conf = {
        "task_type": body.task_type,
        "force_reprocess": body.force_reprocess,
        "sample_rows": body.sample_rows,
        "dataset_version": body.dataset_version,
    }
    return request.app.state.airflow.trigger_run(DAG_ID, conf)


@router.get("/pipeline/runs", dependencies=[Depends(require_auth)])
def list_runs(request: Request, limit: int = DEFAULT_RUN_LIMIT) -> dict:
    """Lists recent pipeline runs, newest first.

    Args:
        request: the FastAPI request.
        limit: how many runs to return.

    Returns:
        `runs`, a list of run summaries. Wrapped in an object rather than
        returned as a bare array so fields can be added later without
        breaking the frontend.

    Example:
        # GET /api/pipeline/runs?limit=5
        # {"runs": [{"run_id": "...", "state": "success",
        #            "task_type": "regression", ...}]}
    """
    return {"runs": request.app.state.airflow.list_runs(DAG_ID, limit)}


@router.get("/pipeline/runs/{run_id}", dependencies=[Depends(require_auth)])
def get_run(request: Request, run_id: str) -> dict:
    """Reports one run and the state of each of its tasks.

    Args:
        request: the FastAPI request.
        run_id: the run to describe.

    Returns:
        `run_id`, `state` and `tasks`. This is what draws the stage strip on
        the overview screen.

    Example:
        # GET /api/pipeline/runs/manual__2026-...
        # {"run_id": "...", "state": "running",
        #  "tasks": [{"task_id": "extract", "state": "success",
        #             "try_number": 1, "duration": 12.5}]}
    """
    return request.app.state.airflow.get_run(DAG_ID, run_id)
