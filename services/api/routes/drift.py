"""Serving the drift verdicts to the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..deps import require_auth

router = APIRouter()

DEFAULT_HISTORY_LIMIT = 20


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
