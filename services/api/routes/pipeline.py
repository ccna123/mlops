"""Starting pipeline runs and reporting what they are doing.

A run takes minutes, so every endpoint here is a snapshot: trigger returns
as soon as Airflow has queued the run, and the dashboard polls for the rest.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from ml_common.estimators import ESTIMATOR_NAMES

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
        #  "sample_rows": 1000, "dataset_version": "v1",
        #  "tune_hyperparameters": false}
    """

    task_type: Literal["regression", "classification"]
    force_reprocess: bool = False
    sample_rows: int | None = Field(default=None, gt=0)
    dataset_version: str = "v1"
    estimator_name: str | None = None
    tune_hyperparameters: bool = False

    @model_validator(mode="after")
    def _estimator_belongs_to_the_task_type(self) -> RunRequest:
        """Refuses an estimator the chosen task type does not offer.

        Returns:
            The validated request.

        Raises:
            ValueError: when `estimator_name` is not one of the names
                `ml_common.estimators` accepts for this `task_type`. FastAPI
                turns it into a 422. Checked here rather than left to the
                train container, where it would surface minutes later as a
                failed stage.
        """
        if self.estimator_name is None:
            return self
        allowed = ESTIMATOR_NAMES[self.task_type]
        if self.estimator_name not in allowed:
            raise ValueError(f"estimator for {self.task_type} must be one of {allowed}")
        return self


@router.post("/pipeline/run", dependencies=[Depends(require_auth)])
def trigger_run(request: Request, body: RunRequest) -> dict:
    """Queues a pipeline run with the settings the dashboard chose.

    Args:
        request: the FastAPI request, used to reach the injected client.
        body: the run settings. `sample_rows` is how many TRAIN rows to sample
            at random (the test set never shrinks); None means every train
            row. A value of 0 or less is rejected rather than silently
            treated as "all", which would start a two-million-row run on a
            machine that asked for a small one.

    Returns:
        `run_id`, `dag_id` and `state`. The run is only QUEUED - it has not
        finished, and it will take minutes - and longer still when
        `tune_hyperparameters` is set, since the train stage then runs a
        GridSearchCV instead of fitting once.

    Example:
        # -> {"run_id": "manual__2026-09-20T10:00:00+00:00",
        #     "dag_id": "ml_pipeline", "state": "queued"}
    """
    conf = {
        "task_type": body.task_type,
        "force_reprocess": body.force_reprocess,
        "sample_rows": body.sample_rows,
        "dataset_version": body.dataset_version,
        "estimator_name": body.estimator_name,
        "tune_hyperparameters": body.tune_hyperparameters,
    }
    return request.app.state.airflow.trigger_run(DAG_ID, conf)


@router.get("/estimators", dependencies=[Depends(require_auth)])
def list_estimators() -> dict:
    """Lists the estimators each task type offers.

    Read straight from `ml_common.estimators`, the same table the train stage
    validates against, so the dropdown cannot drift from what a run will
    actually accept.

    Args:
        None.

    Returns:
        One key per task type holding its estimator names in the order they
        are declared. Every name offered is a real candidate - since
        2026-09-23 there is no separate "diagnostic" group of estimators that
        exist only to exercise the promotion gates; ml_common.estimators
        dropped that pair (hist_gradient_boosting_weak and dummy) along with
        narrowing the list to three names per task type.

    Example:
        # GET /api/estimators
        # {"regression": ["ridge", "xgboost", "random_forest"],
        #  "classification": ["xgboost", "svm", "random_forest"]}
    """
    return {task_type: list(names) for task_type, names in ESTIMATOR_NAMES.items()}


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
