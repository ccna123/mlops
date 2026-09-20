"""HTTP surface the dashboard talks to, and nothing else talks to.

Every collaborator is injected, the same way `services/serving/app.py`
injects its registry and its flush function. That is what lets the routes
be tested without Airflow, MLflow or MinIO running - serving's suite proves
the pattern works, at 20 tests in four seconds.

The dashboard reaches Airflow, MLflow and object storage ONLY through here.
Section 8.2 of the design doc gives the reason: credentials would otherwise
live in the browser, CORS would have to open for several services, and
every backend swap would become a frontend change.
"""

from __future__ import annotations

from fastapi import FastAPI

from .routes import health


def create_app(
    airflow=None,
    registry=None,
    reports=None,
    probes: dict | None = None,
) -> FastAPI:
    """Builds the API application.

    Args:
        airflow: client for Airflow's REST API. None builds the real one.
        registry: client for the MLflow Model Registry. None builds the real one.
        reports: reader for drift summaries in object storage. None builds
            the real one.
        probes: health probes, name to a zero-argument callable. None builds
            one probe per real dependency.

    Returns:
        A FastAPI app serving everything under `/api`.

    Example:
        # Production - module level, everything real:
        app = create_app()

        # A test - no infrastructure at all:
        app = create_app(probes={"airflow": lambda: True})
    """
    app = FastAPI(title="mlops control room api")
    app.state.airflow = airflow
    app.state.registry = registry
    app.state.reports = reports
    app.state.probes = probes if probes is not None else {}

    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
