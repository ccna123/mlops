"""Tests for `_feature_margins` in `stages/monitor/main.py`.

Every other stage's `main.py` is thin glue over `common/ml_common`, proven
correct live via `scripts/verify_monitoring.ps1` and the docker runs in
task-11's report rather than unit tests - there is no `stages/*/tests/`
anywhere in this repo. `_feature_margins` earns an exception: its failure
mode on malformed input - silently dropping entries and returning a short
or empty list - is exactly "a green badge produced by broken extraction",
the failure this whole plan exists to catch. It also imports no Evidently
at module scope (only the parsed shape of `results.dict()`), so it is just
as testable as anything in `ml_common.drift`.

`stages/` has no `__init__.py` anywhere - stage scripts are not a package,
by design, so each Docker image only copies the one `main.py` it needs.
Rather than add package structure to production code for one test file,
this loads `stages/monitor/main.py` directly by path.

SKIPPED INSIDE THE ml-base CONTAINER, ON PURPOSE. `ml-base:latest` COPYs
only `common/` - `docker run --rm ml-base:latest sh -c "ls /app"` prints
just `common`, nothing else. `stages/monitor/main.py` does not exist in
that image, so loading it there would raise `FileNotFoundError` at
COLLECTION time, which aborts pytest's entire run, not just this one file
(`ERROR common/tests/test_monitor_feature_margins.py - FileNotFoundError`,
`Interrupted: 1 error during collection`) - failing the plan's Definition
of Done item 2, "tests pass in the container under Python 3.12", for
every test in the suite, not just these five. The module-level
`pytestmark` below guards against exactly that: it is computed and
evaluated BEFORE `_load_monitor_main()` is ever called, so collection
never touches the missing file inside the container. This file runs (not
skips) on the dev machine and wherever CI checks out the full repo, both
of which have `stages/` on disk. DO NOT "fix" this skip by adding
`stages/` to `ml-base`'s Dockerfile, by adding `__init__.py` under
`stages/` to make it importable normally, or by moving this file/logic
into `common/ml_common/` to dodge the problem - see the module-docstring
paragraphs above for why `_feature_margins` belongs with the monitor
stage and why `stages/` has no package structure. The correct fix, if this
skip ever needs revisiting, is to keep it and just make sure the container
suite is run with the coordinator's exact container test command
alongside the dev-machine one, not to make the skip stop triggering.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MONITOR_MAIN_PATH = Path(__file__).resolve().parents[2] / "stages" / "monitor" / "main.py"

pytestmark = pytest.mark.skipif(
    not _MONITOR_MAIN_PATH.exists(),
    reason=(
        "stages/monitor/main.py not present - the ml-base image copies only "
        "common/, so this test runs on the dev machine and in CI, not in the "
        "container suite."
    ),
)


def _load_monitor_main():
    """Loads stages/monitor/main.py as a module without a package around it.

    Only called when `_MONITOR_MAIN_PATH` is already known to exist - see
    the module-level skip guard above. Calling this unconditionally at
    import time is exactly what broke the container test suite: inside
    ml-base, the file is absent and `spec_from_file_location` /
    `exec_module` raise `FileNotFoundError` during collection, before the
    skip marker ever gets a chance to apply.

    Returns:
        The executed module object, with `_feature_margins` and friends as
        attributes. Re-running this in the same process re-executes the
        module, which is harmless: `main.py`'s only top-level side effects
        are `def`s and constant assignments, guarded from running by its
        own `if __name__ == "__main__":` block.
    """
    spec = importlib.util.spec_from_file_location("monitor_main_under_test", _MONITOR_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


monitor_main = _load_monitor_main() if _MONITOR_MAIN_PATH.exists() else None


def _value_drift(column: str, threshold: float, value: float) -> dict:
    """Builds one well-formed `evidently:metric_v2:ValueDrift` entry."""
    return {
        "config": {
            "type": monitor_main.VALUE_DRIFT_TYPE,
            "column": column,
            "method": "Jensen-Shannon distance",
            "threshold": threshold,
        },
        "value": value,
    }


def test_feature_margins_returns_one_value_per_usable_entry():
    summary = {
        "metrics": [
            _value_drift("city", 0.1, 0.775448),
            _value_drift("bedrooms", 0.1, 0.051171),
        ]
    }
    assert monitor_main._feature_margins(summary) == pytest.approx(
        [0.775448 - 0.1, 0.051171 - 0.1]
    )


def test_feature_margins_raises_when_every_entry_is_missing_threshold():
    # Every ValueDrift entry found, but none usable - this is the "green
    # badge from broken extraction" case: silently returning [] would make
    # feature_margin_severity report "ok" on a report nobody could read.
    summary = {
        "metrics": [
            {"config": {"type": monitor_main.VALUE_DRIFT_TYPE, "column": "city"}, "value": 0.9},
            {
                "config": {"type": monitor_main.VALUE_DRIFT_TYPE, "column": "zipcode"},
                "value": 0.8,
            },
        ]
    }
    with pytest.raises(KeyError):
        monitor_main._feature_margins(summary)


def test_feature_margins_raises_when_there_are_no_value_drift_entries_at_all():
    # A drift report with zero per-column results means extraction itself
    # is broken, not that nothing drifted.
    summary = {
        "metrics": [
            {
                "config": {"type": monitor_main.DRIFTED_COLUMNS_COUNT_TYPE},
                "value": {"count": 0, "share": 0.0},
            }
        ]
    }
    with pytest.raises(KeyError):
        monitor_main._feature_margins(summary)


def test_feature_margins_raises_on_completely_empty_metrics():
    with pytest.raises(KeyError):
        monitor_main._feature_margins({"metrics": []})


def test_feature_margins_skips_one_malformed_entry_and_keeps_the_good_one():
    # Partial data is still usable - one odd column must not take the
    # whole run down. Only the all-or-nothing case is loud.
    summary = {
        "metrics": [
            _value_drift("city", 0.1, 0.775448),
            {
                "config": {"type": monitor_main.VALUE_DRIFT_TYPE, "column": "zipcode"},
                "value": 0.825054,
                # threshold missing on purpose
            },
        ]
    }
    assert monitor_main._feature_margins(summary) == pytest.approx([0.775448 - 0.1])
