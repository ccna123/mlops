"""Serving the drift verdicts to the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from ..deps import require_auth

router = APIRouter()

DEFAULT_HISTORY_LIMIT = 20

# monitoring_dag fans out to one task per task_type on its own, so a run
# covers every model at once and there is nothing per-model to pass in.
MONITORING_DAG_ID = "monitoring_dag"


@router.post("/drift/run", dependencies=[Depends(require_auth)])
def run_monitoring(request: Request) -> dict:
    """Queues a monitoring run that recomputes drift for every model.

    Takes no parameters: `monitoring_dag` builds one task per task_type
    itself, so a run always covers both models.

    Args:
        request: the FastAPI request.

    Returns:
        `run_id`, `dag_id` and `state`, as soon as Airflow has queued the run.
        The report is not ready yet at that point - the caller polls
        `/drift/latest` afterwards.

    Raises:
        Exception: an Airflow failure escapes as a 500. Note that a queued run
            only starts if `monitoring_dag` is unpaused; this endpoint cannot
            tell the difference and neither can the response.

    Example:
        # POST /api/drift/run
        # -> {"run_id": "manual__2026-09-21T11:20:00+00:00",
        #     "dag_id": "monitoring_dag", "state": "queued"}
    """
    return request.app.state.airflow.trigger_run(MONITORING_DAG_ID, {})


@router.get("/drift/latest", dependencies=[Depends(require_auth)])
def latest(request: Request, model_name: str) -> dict:
    """Returns the most recent drift verdict for one model.

    Args:
        request: the FastAPI request.
        model_name: which registered model.

    Returns:
        The summary as the monitor stage wrote it, including `severity`, the
        three `parts`, and `report_key`. Note that `parts.performance` can be
        `insufficient_data`, which is NOT the same as `ok` - ground truth
        arrives after the prediction it describes, so early on there is
        simply nothing to measure.

    Raises:
        HTTPException: 404 when monitoring has never run for this model. The
            UI shows an empty state for that, not an error. Object storage
            being unreachable or refusing the credentials is NOT a 404: it
            escapes as a 500, so an outage never reads as "no report yet".

    Example:
        # GET /api/drift/latest?model_name=house_price_regressor
        # {"severity": "high",
        #  "parts": {"feature": "ok", "prediction": "high",
        #            "performance": "high"}, ...}
    """
    summary = request.app.state.reports.latest(model_name)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"no drift report yet for {model_name}")
    return summary


@router.get("/drift/report", dependencies=[Depends(require_auth)], response_class=HTMLResponse)
def report(request: Request, model_name: str, run_id: str) -> HTMLResponse:
    """Serves the Evidently HTML report of one monitoring run.

    The dashboard renders this in a sandboxed iframe. It exists so the browser
    never talks to MinIO directly: doing that would put storage credentials in
    the page and break the rule that the frontend speaks only to this API
    (design doc section 8.2).

    What it contains is Evidently's own per-column view of FEATURE drift for
    that one run - not the three verdicts, not performance, and nothing about
    any other run. It is the detail behind one point of the history, not a
    replacement for it.

    Args:
        request: the FastAPI request.
        model_name: the registered model.
        run_id: which monitoring run's report to serve.

    Returns:
        The report as `text/html`, exactly as the monitor stage wrote it.

    Raises:
        HTTPException: 404 when that run wrote no report - normal for a run
            whose window held no traffic, since the monitor stops before
            Evidently and records `report_key: null`. Storage being
            unreachable is not a 404: it escapes as a 500.

    Example:
        # GET /api/drift/report?model_name=house_price_regressor&run_id=20260920T075645
        # -> 200 text/html

    Note:
        `run_id` reaches the key from the browser, but `report_key` always
        appends "/evidently.html", so no other kind of object in the bucket
        can be addressed through it.
    """
    html = request.app.state.reports.html(model_name, run_id)
    if html is None:
        raise HTTPException(
            status_code=404, detail=f"no Evidently report for run {run_id} of {model_name}"
        )
    return HTMLResponse(content=html)


@router.get("/drift/history", dependencies=[Depends(require_auth)])
def history(
    request: Request,
    model_name: str,
    limit: int = Query(DEFAULT_HISTORY_LIMIT, gt=0),
) -> dict:
    """Returns recent drift verdicts, newest first.

    Args:
        request: the FastAPI request.
        model_name: which registered model.
        limit: how many verdicts to return. Must be greater than zero: a
            negative value would slice off only the newest run instead of
            capping the list, and zero would answer "no history" for a model
            that has some. Both are rejected with a 422.

    Returns:
        `history`. An empty list when monitoring has never run - unlike
        `latest`, absence here is not an error, because "no history" is a
        chart with no points rather than a missing page.

    Example:
        # GET /api/drift/history?model_name=house_price_regressor&limit=5
        # {"history": [{"run_id": "...", "severity": "warning", ...}]}
    """
    return {"history": request.app.state.reports.history(model_name, limit)}
