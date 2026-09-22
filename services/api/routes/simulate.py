"""Sending simulated traffic through serving, so drift has something to measure.

Drift is computed from the predictions serving logged. With no traffic there
is nothing to compare against the training data, and every verdict reads
`insufficient_data` - which is why the dashboard needs a way to produce
traffic on demand rather than waiting for a real caller that does not exist
on a dev box.

The work itself happens in the `ml-agent` container, started by the
`traffic_agent` DAG. Running it inside this process instead would pull the
raw dataset into the API's memory (about a gigabyte, measured in Plan 5a)
for a job that is not the API's to do.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from services.agent.scenarios import SCENARIOS

from ..deps import require_auth

router = APIRouter()

DAG_ID = "traffic_agent"

# One request is one real HTTP call to serving, sent in sequence. 5000 already
# takes minutes; an unbounded count would hold the container open for hours
# and fill the inference log while it did.
MAX_COUNT = 5_000
DEFAULT_COUNT = 300


class SimulateRequest(BaseModel):
    """What the dashboard sends to start a batch of simulated traffic.

    Example:
        # POST /api/simulate
        # {"scenario": "market_shift", "task_type": "regression", "count": 300}
    """

    # Literal rather than a validator so the accepted names appear in the
    # OpenAPI schema, and so a typo is a 422 before Airflow is ever called.
    scenario: Literal[SCENARIOS] = "none"  # type: ignore[valid-type]
    task_type: Literal["regression", "classification"]
    count: int = Field(default=DEFAULT_COUNT, gt=0, le=MAX_COUNT)


@router.post("/simulate", dependencies=[Depends(require_auth)])
def simulate(request: Request, body: SimulateRequest) -> dict:
    """Queues a run that sends simulated traffic to serving.

    Args:
        request: the FastAPI request, used to reach the injected client.
        body: which scenario to simulate, against which model, how many
            requests. `scenario="none"` is undistorted traffic drawn from real
            rows - useful for proving the path works, but it produces no drift
            by design.

    Returns:
        `run_id`, `dag_id` and `state`, as soon as Airflow has queued the run.
        The traffic has NOT been sent yet at that point, and the drift report
        does not exist either: the caller polls `/simulate/status`, then
        triggers `/drift/run` once the traffic run has finished.

    Example:
        # -> {"run_id": "manual__2026-09-22T10:00:00+00:00",
        #     "dag_id": "traffic_agent", "state": "queued"}
    """
    conf = {
        "scenario": body.scenario,
        "task_type": body.task_type,
        "count": body.count,
    }
    return request.app.state.airflow.trigger_run(DAG_ID, conf)


@router.get("/scenarios", dependencies=[Depends(require_auth)])
def list_scenarios() -> dict:
    """Lists the market scenarios the agent can simulate.

    Read straight from `services.agent.scenarios`, the module the agent itself
    validates against, so the dropdown cannot offer a scenario a run would
    reject.

    Args:
        None.

    Returns:
        `scenarios`, in declaration order, which puts undistorted traffic
        first. What each one does to the data is the agent's docstring, not
        this list - the UI labels them, but the names come from here.

    Example:
        # GET /api/scenarios
        # {"scenarios": ["none", "price_inflation", "market_rally",
        #                "market_shift", "new_segment"]}
    """
    return {"scenarios": list(SCENARIOS)}


@router.get("/simulate/status", dependencies=[Depends(require_auth)])
def status(request: Request) -> dict:
    """Reports the most recent traffic run, so the UI knows when it finished.

    Without this the dashboard could only say "queued" and leave the user
    guessing when the traffic has actually landed in the inference log - the
    exact confusion a queued run of a paused DAG caused on 2026-09-21.

    Args:
        request: the FastAPI request.

    Returns:
        `run` with `run_id`, `state`, `started_at` and `ended_at`, or None
        when traffic has never been sent. None is a normal first-time state,
        not an error, so it is a 200 rather than a 404.

    Example:
        # GET /api/simulate/status
        # {"run": {"run_id": "manual__2026-09-22T10:00:00+00:00",
        #          "state": "success", "started_at": "...", "ended_at": "..."}}
    """
    runs = request.app.state.airflow.list_runs(DAG_ID, 1)
    return {"run": runs[0] if runs else None}
