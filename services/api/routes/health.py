"""Reports whether each thing the dashboard depends on is reachable."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..deps import require_auth

router = APIRouter()


def build_health(probes: dict) -> dict:
    """Runs every dependency probe and summarises the result.

    Args:
        probes: name to a zero-argument callable returning True when that
            dependency answers. A probe that raises counts as down - the
            dashboard needs an answer, not a traceback.

    Returns:
        `status`, "ok" when every probe passed and "degraded" otherwise, and
        `services`, each probe's name mapped to "ok" or "down".

    Example:
        build_health({"airflow": lambda: True, "mlflow": lambda: False})
        # -> {"status": "degraded",
        #     "services": {"airflow": "ok", "mlflow": "down"}}
    """
    services: dict[str, str] = {}
    for name, probe in probes.items():
        try:
            services[name] = "ok" if probe() else "down"
        except Exception:  # noqa: BLE001 - any failure means "not reachable"
            services[name] = "down"
    healthy = all(state == "ok" for state in services.values())
    return {"status": "ok" if healthy else "degraded", "services": services}


@router.get("/health", dependencies=[Depends(require_auth)])
def health(request: Request) -> dict:
    """Reports the state of every dependency the dashboard needs.

    Args:
        request: the FastAPI request, used to read the injected probes.

    Returns:
        `status` ("ok" or "degraded") and `services`. Always HTTP 200 -
        "degraded" is a state to read, not a request that failed, the same
        contract serving's /health has used since plan 3.

    Example:
        # GET /api/health
        # {"status": "degraded",
        #  "services": {"airflow": "ok", "mlflow": "ok", "minio": "ok",
        #               "serving": "down", "postgres": "ok"}}
    """
    return build_health(request.app.state.probes)
