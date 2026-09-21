"""Listing model versions and promoting one to champion."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from ..clients.registry import RegistryNotFoundError
from ..deps import require_auth

router = APIRouter()

# MLflow numbers registered model versions with positive integers. Anything
# else reaches its API as INVALID_PARAMETER_VALUE and used to come back as a
# 500; refusing it here makes it the caller's 422 instead.
VERSION_PATTERN = r"^[0-9]+$"


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
def promote(
    request: Request,
    name: str,
    version: Annotated[str, Path(pattern=VERSION_PATTERN)],
) -> dict:
    """Moves the champion alias onto one version.

    Args:
        request: the FastAPI request.
        name: the registered model.
        version: the version to promote, digits only (e.g. "4").

    Returns:
        `name`, `version` and `alias`.

    Raises:
        HTTPException: 422 when `version` is not made of digits only - raised
            by FastAPI before this runs, so "abc" never reaches MLflow.
            404 when the model or version does not exist. This is
            a real write against the Registry, so the UI must confirm before
            calling it and must not report success on a failure.
        Exception: any failure other than not-found - MLflow down, a timeout -
            is deliberately not caught and escapes as a 500, because "the
            Registry is unreachable" and "that version does not exist" call
            for different reactions from the UI.

    Example:
        # POST /api/models/house_price_regressor/4/promote
        # -> {"name": "house_price_regressor", "version": "4",
        #     "alias": "champion"}
    """
    try:
        return request.app.state.registry.promote(name, version)
    except RegistryNotFoundError as err:
        raise HTTPException(status_code=404, detail=f"cannot promote: {err}") from err
