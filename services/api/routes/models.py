"""Listing model versions and promoting one to champion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import require_auth

router = APIRouter()


@router.get("/models", dependencies=[Depends(require_auth)])
def list_models(request: Request) -> dict:
    """Lists registered models, their versions and their metrics.

    Args:
        request: the FastAPI request.

    Returns:
        `models`. Each version's `metrics` holds whichever keys that model
        logged - regression and classification differ, and the UI must read
        the keys rather than assume a fixed set.

    Example:
        # GET /api/models
        # {"models": [{"name": "house_price_regressor",
        #              "task_type": "regression",
        #              "versions": [{"version": "3",
        #                            "metrics": {"rmse": 41203.7, ...},
        #                            "is_champion": true}]}]}
    """
    return {"models": request.app.state.registry.list_models()}


@router.post("/models/{name}/{version}/promote", dependencies=[Depends(require_auth)])
def promote(request: Request, name: str, version: str) -> dict:
    """Moves the champion alias onto one version.

    Args:
        request: the FastAPI request.
        name: the registered model.
        version: the version to promote.

    Returns:
        `name`, `version` and `alias`.

    Raises:
        HTTPException: 404 when the model or version does not exist. This is
            a real write against the Registry, so the UI must confirm before
            calling it and must not report success on a failure.

    Example:
        # POST /api/models/house_price_regressor/4/promote
        # -> {"name": "house_price_regressor", "version": "4",
        #     "alias": "champion"}
    """
    try:
        return request.app.state.registry.promote(name, version)
    except Exception as err:  # noqa: BLE001 - surfaced as 404 with the reason
        raise HTTPException(status_code=404, detail=f"cannot promote: {err}") from err
