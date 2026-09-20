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

    Returns:
        Nothing. The result leaves as one prefixed line on stdout, which
        DockerOperator captures; `parse_result` is what reads it back.

    Raises:
        TypeError: when payload is not a dict.

    Example:
        # Last line of every stage's main(). Human-readable logs go to stderr,
        # the machine-readable result goes through here and nowhere else:
        print(f"wrote {n} rows", file=sys.stderr)
        emit_result({"fingerprint": "3f0a9c1d5e2b7a48", "row_count": 200000})
        # stdout gets exactly:
        # XCOM_RESULT {"fingerprint": "3f0a9c1d5e2b7a48", "row_count": 200000}
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

    Args:
        lines: every line of the stage's merged stdout and stderr, in the order
            captured. Non-string entries are skipped rather than crashing.

    Returns:
        The payload `emit_result` was given, decoded from JSON.

    Raises:
        ValueError: when no marked line is present — the stage died before
            emitting, and treating that as an empty result would let the DAG
            carry on with nothing.

    Example:
        parse_result([
            "reading raw data",                       # stderr noise
            'XCOM_RESULT {"fingerprint": "3f0a", "row_count": 200000}',
            "wrote 200000 rows",                      # landed AFTER the result
        ])
        # -> {"fingerprint": "3f0a", "row_count": 200000}
        # Position does not matter, only the marker. That log order is real:
        # replaying one stage five times put the JSON last only twice.
    """
    for line in reversed(lines):
        if not isinstance(line, str):
            continue
        stripped = line.strip()
        if stripped.startswith(RESULT_PREFIX):
            return json.loads(stripped[len(RESULT_PREFIX) :])
    raise ValueError(f"no {RESULT_PREFIX.strip()} line in stage output: {lines!r}")
