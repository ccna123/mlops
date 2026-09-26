"""Checks the Prometheus config and every PromQL query with promtool (02 11.6).

The consistency of the Grafana files is checked by common/tests/test_alert_config.py;
this adds what only Prometheus itself can tell: that the config loads and that
every query in the alert rules and the dashboard parses.

Run from the repo root with promtool on PATH (CI downloads it):
    python scripts/check_alert_config.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def queries() -> list[tuple[str, str]]:
    """Collects every PromQL query the alert rules and the dashboard use.

    Args:
        None. Reads docker/grafana/provisioning/alerting/rules.yml and
        docker/grafana/dashboards/mlops.json.

    Returns:
        `(name, expr)` pairs.

    Example:
        queries()[0]  # -> ("mlops_level_high_A", "max by (...) (ml_monitoring_level)")
    """
    found = []
    rules = yaml.safe_load((ROOT / "docker/grafana/provisioning/alerting/rules.yml").read_text())
    for group in rules["groups"]:
        for rule in group["rules"]:
            for query in rule["data"]:
                expr = query["model"].get("expr")
                if expr:
                    found.append((f"{rule['uid']}_{query['refId']}".replace("-", "_"), expr))
    dashboard = json.loads((ROOT / "docker/grafana/dashboards/mlops.json").read_text())
    for panel in dashboard["panels"]:
        for target in panel["targets"]:
            found.append((f"panel{panel['id']}_{target['refId']}", target["expr"]))
    return found


def main() -> int:
    """Runs `promtool check config` and `promtool check rules`.

    Args:
        None.

    Returns:
        0 when both pass, 1 otherwise (promtool's output explains why).
    """
    config = subprocess.run(
        ["promtool", "check", "config", str(ROOT / "docker/prometheus/prometheus.yml")],
        check=False,
    )
    rules = {"groups": [{"name": "grafana_queries",
                         "rules": [{"record": f"check:{name}", "expr": expr}
                                   for name, expr in queries()]}]}
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as handle:
        yaml.safe_dump(rules, handle)
    parsed = subprocess.run(["promtool", "check", "rules", handle.name], check=False)
    return 0 if config.returncode == 0 and parsed.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
