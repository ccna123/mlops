"""The one place that defines how a stage hands its result back to Airflow.

DockerOperator reads a container's stdout and stderr merged into one stream,
and the daemon does not guarantee the order of two writes that land
microseconds apart on different pipes. Relying on the result being the last
line is therefore a race: replaying one stage five times put the JSON last
only twice.

So the result line marks itself. Every stage calls emit_result, nothing prints
the result by hand, and a new stage cannot get the contract wrong by accident.
"""

from __future__ import annotations

import json
import sys

RESULT_PREFIX = "XCOM_RESULT "


def emit_result(payload: dict) -> None:
    """Writes the one machine-readable line a stage produces.

    Args:
        payload: the values the DAG passes on through XCom. Must be a dict —
            a bare number or string would be ambiguous against log output.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"stage result must be a dict, got: {type(payload).__name__}")
    # Drain stderr first so the human-readable log stays ahead of the result in
    # the common case. Correctness does not depend on it; the prefix does.
    sys.stderr.flush()
    print(f"{RESULT_PREFIX}{json.dumps(payload)}", flush=True)


def parse_result(lines: list[str]) -> dict:
    """Finds the result a stage emitted, wherever it landed in the merged log.

    Scanned from the end: a stage emits exactly one result and emits it last,
    so on the rare interleave the later match is still the right one.
    """
    for line in reversed(lines):
        if not isinstance(line, str):
            continue
        stripped = line.strip()
        if stripped.startswith(RESULT_PREFIX):
            return json.loads(stripped[len(RESULT_PREFIX) :])
    raise ValueError(f"no {RESULT_PREFIX.strip()} line in stage output: {lines!r}")
