"""Starting pipeline runs and reporting what they are doing.

A run takes minutes, so every endpoint here is a snapshot: trigger returns
as soon as Airflow has queued the run, and the dashboard polls for the rest.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..clients.airflow import AirflowNotFoundError
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

    Raises:
        HTTPException: 404 when Airflow has no run with that id. Nothing else
            is caught: Airflow being down, refusing the credentials or failing
            escapes as a 500, because "the run does not exist" and "Airflow is
            unreachable" call for different reactions from the UI.

    Example:
        # GET /api/pipeline/runs/manual__2026-...
        # {"run_id": "...", "state": "running",
        #  "tasks": [{"task_id": "extract", "state": "success",
        #             "try_number": 1, "duration": 12.5}]}
    """
    try:
        return request.app.state.airflow.get_run(DAG_ID, run_id)
    except AirflowNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


MAX_LOG_LINES = 2000

# What an Airflow task id may look like. The value becomes part of a URL path
# on the way to Airflow, so anything outside this shape (slashes, dots, "?",
# spaces) is refused with a 422 instead of being forwarded.
TASK_ID_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_-]*$"


def filter_log_lines(text: str, level: str | None, keyword: str | None) -> tuple[list[str], bool]:
    """Splits a log into lines and keeps only the ones asked for.

    Args:
        text: the raw log text as Airflow returned it.
        level: keep only lines mentioning this level as a whole word,
            case-insensitively, so `level=ERROR` does not also match a line
            reading "no errors found". None keeps every level.
        keyword: keep only lines containing this text, case-insensitively,
            as a plain substring - this is free-text search, not level
            matching, so `q=error` DOES match "no errors found". None keeps
            every line.

    Returns:
        A tuple of (lines, truncated). Filtering happens here rather than in
        the browser so a run with thousands of lines does not cross the
        network only to be thrown away - section 8.1 names doing this in JS
        as one of the things the old frontend got wrong. `truncated` is True
        when lines were dropped at MAX_LOG_LINES, so the UI can say so
        instead of silently showing less than there is. Blank lines are kept
        when unfiltered, since Airflow tracebacks and section separators use
        them; a `level` or `q` needle can never match a blank line, so it
        drops out naturally as soon as either filter is applied.

    Example:
        filter_log_lines(text, level="ERROR", keyword=None)
        # -> (["[2026-09-20 10:00:03] ERROR - could not parse zipcode"], False)
    """
    lines = text.splitlines()
    if level:
        pattern = re.compile(rf"\b{re.escape(level)}\b", re.IGNORECASE)
        lines = [line for line in lines if pattern.search(line)]
    if keyword:
        needle = keyword.lower()
        lines = [line for line in lines if needle in line.lower()]
    truncated = len(lines) > MAX_LOG_LINES
    return lines[:MAX_LOG_LINES], truncated


@router.get("/pipeline/runs/{run_id}/logs", dependencies=[Depends(require_auth)])
def get_logs(
    request: Request,
    run_id: str,
    stage: Annotated[str, Query(pattern=TASK_ID_PATTERN, min_length=1, max_length=250)],
    level: str | None = None,
    q: str | None = None,
    try_number: int = 1,
) -> dict:
    """Reads one task's log, filtered on the server.

    Args:
        request: the FastAPI request.
        run_id: the run whose log is wanted.
        stage: which task's log - required, because a run has seven tasks and
            "the log" is not a thing that exists. Must look like a task id
            (letters, digits, "_" and "-", not starting with "-", at most 250
            characters); anything else is a 422.
        level: keep only lines at this level.
        q: keep only lines containing this text.
        try_number: which attempt; Airflow numbers them from 1. Defaults to
            the FIRST attempt, so a retried task's first try_number may be
            stale - callers should pass the try_number that
            `GET /pipeline/runs/{run_id}` already reports per task rather
            than relying on this default.

    Returns:
        `lines` and `truncated`. The first two or three lines of an unfiltered
        result are not the task's own output: Airflow prefixes the worker host
        and a "Found local files" banner.

    Raises:
        HTTPException: 404 when Airflow has no such run (a `run_id` made only
            of dots counts as no such run and is never sent), or no such task
            (`stage`) in that run. 422 when `stage` is not shaped like a task
            id. NOT a 404: a `try_number` that has no log.
            Airflow answers 200 there and its own error text ("*** Could not
            read served logs: 403 ...") comes back in `lines` as if it were
            the log, so pass the `try_number` that the run detail reports for
            the task. Nothing else is caught: Airflow being down, refusing the
            credentials or failing escapes as a 500.

    Example:
        # GET /api/pipeline/runs/manual__.../logs?stage=validate&level=ERROR
        # {"lines": ["[...] ERROR - target source missing in 62% of rows"],
        #  "truncated": false}
    """
    try:
        text = request.app.state.airflow.get_logs(DAG_ID, run_id, stage, try_number)
    except AirflowNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    lines, truncated = filter_log_lines(text, level, q)
    return {"lines": lines, "truncated": truncated}
