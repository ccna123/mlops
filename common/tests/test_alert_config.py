"""The Grafana and Prometheus configuration agrees with itself and with the code.

Runs wherever the repo is checked out (dev machine, CI); skipped inside the
ml-base image, which holds only common/.
"""

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
PROVISIONING = ROOT / "docker" / "grafana" / "provisioning"

pytestmark = pytest.mark.skipif(not PROVISIONING.exists(), reason="docker/ not present")


def _load(relative: str):
    return yaml.safe_load((PROVISIONING / relative).read_text(encoding="utf-8"))


def _rules():
    return [rule for group in _load("alerting/rules.yml")["groups"] for rule in group["rules"]]


def test_every_rule_is_well_formed():
    datasource_uids = {d["uid"] for d in _load("datasources/prometheus.yml")["datasources"]}
    uids = [rule["uid"] for rule in _rules()]
    assert len(uids) == len(set(uids)), "rule uids must be unique"
    for rule in _rules():
        ref_ids = {query["refId"] for query in rule["data"]}
        assert rule["condition"] in ref_ids, rule["uid"]
        for query in rule["data"]:
            assert query["datasourceUid"] in datasource_uids | {"__expr__"}, rule["uid"]
            assert query["model"]["refId"] == query["refId"], rule["uid"]
        assert {"summary", "runbook"} <= set(rule["annotations"]), rule["uid"]
        assert rule["noDataState"] == "OK", "no data (nothing monitored yet) is not an alert"


def test_template_dollars_are_escaped_from_env_expansion():
    single_dollar = re.compile(r"(?<!\$)\$(?!\$)[A-Za-z]")
    for rule in _rules():
        for text in rule["annotations"].values():
            assert not single_dollar.search(text), (rule["uid"], text)


def test_every_metric_a_rule_reads_is_emitted_by_the_code():
    code = "".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "common/ml_common/pushgateway.py",
            "dags/run_outcome.py",
            "services/serving/app.py",
        )
    )
    for rule in _rules():
        for query in rule["data"]:
            expr = query["model"].get("expr", "")
            for name in re.findall(r"\b((?:ml|serving)_[a-z_]+?)(?:_bucket)?\b", expr):
                assert re.search(rf"\b{name}\b", code), (
                    f"{rule['uid']} reads {name}, which nothing emits"
                )


def test_alerts_go_to_the_operator_once_a_day_at_most():
    notifications = _load("alerting/notifications.yml")
    names = {point["name"] for point in notifications["contactPoints"]}
    policy = notifications["policies"][0]
    assert policy["receiver"] in names
    assert policy["repeat_interval"] == "24h"
    url = notifications["contactPoints"][0]["receivers"][0]["settings"]["url"]
    assert url == "$ALERT_WEBHOOK_URL", "the channel comes from .env, never the repo"


def test_prometheus_scrapes_serving_and_the_pushgateway():
    config = yaml.safe_load((ROOT / "docker/prometheus/prometheus.yml").read_text())
    targets = {t for job in config["scrape_configs"] for c in job["static_configs"]
               for t in c["targets"]}
    assert {"serving:8000", "pushgateway:9091"} <= targets


def test_dashboard_is_valid_json_on_the_provisioned_datasource():
    dashboard = json.loads((ROOT / "docker/grafana/dashboards/mlops.json").read_text())
    for panel in dashboard["panels"]:
        assert panel["datasource"]["uid"] == "prometheus"
