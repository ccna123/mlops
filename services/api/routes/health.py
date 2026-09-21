"""Reports whether each thing the dashboard depends on is reachable."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request

from ..deps import require_auth

router = APIRouter()

# The most /health will wait for any dependency. A dependency that is down is
# exactly when the dashboard needs an answer, and the client libraries behind
# the probes retry for minutes on their own (boto3 about 20 s, MLflow much
# longer), so the bound is enforced here rather than trusted to them.
PROBE_TIMEOUT_S = 5.0

# Probes whose thread is still running, keyed by (name, probe), each with the
# box that thread will write its outcome into. Module-level so it survives from
# one /health call to the next, which is the point: a probe still running from
# an earlier call must not get a second thread, and the later call needs its
# box to read the outcome from. Keying on the probe callable keeps it per app -
# every `create_app()` builds its own probe closures - and tests that build
# their own fakes cannot see each other's. Entries exist only while a thread
# runs, so nothing accumulates.
_running: dict[tuple[str, Callable[[], bool]], tuple[threading.Thread, dict]] = {}
_running_lock = threading.Lock()


def _run_probe(key: tuple[str, Callable[[], bool]], probe: Callable[[], bool], box: dict) -> None:
    """Runs one probe on its own thread and records how it ended.

    Args:
        key: the (name, probe) entry in `_running` to clear when the probe ends.
        probe: the zero-argument callable to run.
        box: where the outcome goes. Gets `up` (True only when the probe
            returned a truthy value; False when it returned falsy or raised).

    Returns:
        None. The result is written into `box`.

    Example:
        box = {}
        _run_probe(key, lambda: True, box)   # -> box == {"up": True}
    """
    try:
        box["up"] = bool(probe())
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        box["up"] = False
    finally:
        with _running_lock:
            _running.pop(key, None)


def build_health(probes: dict, timeout: float | None = None) -> dict:
    """Runs every dependency probe at once and summarises the result.

    Args:
        probes: name to a zero-argument callable returning True when that
            dependency answers. A probe that raises, returns False, or has not
            finished by the deadline counts as down - the dashboard needs an
            answer, not a traceback and not a hang.
        timeout: seconds to wait for the probes, counted from when this call
            has started or found all of them. None uses `PROBE_TIMEOUT_S`.
            Probes run side by side on daemon threads, so the whole call takes
            about `timeout` at worst however many dependencies hang; a hung
            thread is abandoned rather than waited for. Injectable so tests
            need not wait five seconds.

    Returns:
        `status`, "ok" when every probe passed and "degraded" otherwise, and
        `services`, each probe's name mapped to "ok" or "down", in the order of
        `probes`. A probe whose thread from an earlier call is still running is
        NOT started again: this call waits for that same thread until its own
        deadline and reports what it returned, or "down" if it has not
        finished by then. So two overlapping requests both see a merely slow
        probe as "ok", while a dashboard polling every few seconds still
        leaves at most one stuck thread per dependency instead of one per
        poll.

    Example:
        build_health({"airflow": lambda: True, "mlflow": lambda: False})
        # -> {"status": "degraded",
        #     "services": {"airflow": "ok", "mlflow": "down"}}

        build_health({"airflow": lambda: True, "mlflow": hangs_forever}, timeout=0.2)
        # -> after about 0.2 s: {"status": "degraded",
        #     "services": {"airflow": "ok", "mlflow": "down"}}
    """
    limit = PROBE_TIMEOUT_S if timeout is None else timeout
    started: dict[str, tuple[threading.Thread, dict]] = {}
    for name, probe in probes.items():
        key = (name, probe)
        with _running_lock:
            running = _running.get(key)
            if running is not None:
                # An earlier call's probe is still going. Wait for that one
                # below; a second thread would only pile up behind it.
                started[name] = running
                continue
            box: dict = {}
            thread = threading.Thread(
                target=_run_probe, args=(key, probe, box), name=f"health-probe-{name}", daemon=True
            )
            # Registered and started under one lock, so no other call can find
            # an entry whose thread has not started (joining it would raise).
            try:
                thread.start()
            except RuntimeError:
                # No thread could be created: leave no entry behind that would
                # read "still running" forever, and report the dependency down.
                continue
            _running[key] = (thread, box)
        started[name] = (thread, box)

    deadline = time.monotonic() + limit
    services: dict[str, str] = {}
    for name in probes:
        if name not in started:
            services[name] = "down"
            continue
        thread, box = started[name]
        thread.join(max(0.0, deadline - time.monotonic()))
        finished = not thread.is_alive()
        services[name] = "ok" if finished and box.get("up") else "down"
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
