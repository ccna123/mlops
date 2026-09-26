"""Pushing a batch step's numbers to the Prometheus Pushgateway (02 7.5).

Batch steps finish before Prometheus would come to collect anything, so they
push. Only the standard library is used: every image built on ml-base can push
without another dependency.

Pushing is best effort. Monitoring and training must never fail because the
metric store is down; a failed push is logged and the step carries on.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request

from . import drift

LEVEL_VALUES = {"ok": 0, "warning": 1, "high": 2, drift.INSUFFICIENT: -1}

HELP = {
    "ml_monitoring_level": "Level of a monitoring section: -1 insufficient data, 0 ok, "
    "1 warning, 2 high.",
    "ml_monitoring_consecutive_warnings": "Monitoring runs in a row that ended at warning.",
    "ml_monitoring_rmse_ratio": "Live rmse divided by the champion's test-set rmse.",
    "ml_monitoring_auc_drop": "Champion's test-set auc minus live auc.",
    "ml_monitoring_predictions": "Predictions in the monitoring window.",
    "ml_monitoring_ground_truth_pairs": "Predictions in the window that have ground truth.",
}


def _label_text(labels: dict) -> str:
    """Formats labels the way the Prometheus text format wants them.

    Args:
        labels: label name to value.

    Returns:
        `{a="1",b="x"}`, or "" when there are no labels. Quotes, backslashes
        and newlines inside values are escaped.

    Example:
        _label_text({"part": "feature"})  # -> '{part="feature"}'
    """
    if not labels:
        return ""
    escaped = {
        k: str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        for k, v in labels.items()
    }
    return "{" + ",".join(f'{k}="{v}"' for k, v in sorted(escaped.items())) + "}"


def format_metrics(samples: list[tuple[str, dict, float]]) -> str:
    r"""Renders samples in the Prometheus text exposition format.

    Args:
        samples: `(metric name, labels, value)` triples.

    Returns:
        The text body, one sample per line, ending with a newline. Every
        metric is declared a gauge: each push replaces the previous value.

    Example:
        format_metrics([("ml_monitoring_level", {"part": "feature"}, 1)])
        # -> '# HELP ... \\n# TYPE ml_monitoring_level gauge\\n
        #     ml_monitoring_level{part="feature"} 1\\n'
    """
    lines = []
    declared = set()
    for name, labels, value in samples:
        if name not in declared:
            lines.append(f"# HELP {name} {HELP.get(name, name)}")
            lines.append(f"# TYPE {name} gauge")
            declared.add(name)
        lines.append(f"{name}{_label_text(labels)} {float(value):g}")
    return "\n".join(lines) + "\n"


def monitoring_samples(summary: dict) -> list[tuple[str, dict, float]]:
    """Turns a monitoring summary into the samples the alert rules read.

    Args:
        summary: what the monitor stage wrote.

    Returns:
        Per section: the level (ok 0, warning 1, high 2, insufficient_data
        -1, so it never satisfies an alert rule) and the run of consecutive
        warnings; plus the rmse ratio or auc drop when measured, and the
        prediction and ground-truth counts. Labelled by model and version.

    Example:
        monitoring_samples(summary)
        # -> [("ml_monitoring_level", {"model_name": "m", "model_version": "4",
        #      "part": "feature"}, 1.0), ...]
    """
    base = {"model_name": summary["model_name"], "model_version": str(summary["model_version"])}
    samples = []
    for part, level in summary.get("parts", {}).items():
        samples.append(("ml_monitoring_level", {**base, "part": part}, LEVEL_VALUES[level]))
    for part, count in (summary.get("consecutive_warnings") or {}).items():
        samples.append(("ml_monitoring_consecutive_warnings", {**base, "part": part}, count))
    current = summary.get("current_metrics") or {}
    reference = summary.get("reference_metrics") or {}
    if "rmse" in current and reference.get("rmse"):
        samples.append(("ml_monitoring_rmse_ratio", base, current["rmse"] / reference["rmse"]))
    if "auc" in current and "auc" in reference:
        samples.append(("ml_monitoring_auc_drop", base, reference["auc"] - current["auc"]))
    samples.append(("ml_monitoring_predictions", base, summary.get("n_predictions", 0)))
    samples.append(("ml_monitoring_ground_truth_pairs", base, summary.get("n_ground_truth", 0)))
    return samples


def push(samples: list[tuple[str, dict, float]], job: str, grouping: dict,
         url: str | None = None) -> bool:
    """Replaces one group of metrics on the Pushgateway.

    Args:
        samples: what `format_metrics` renders.
        job: the Pushgateway job name.
        grouping: labels that identify the group, e.g. {"model_name": ...}.
            A later push with the same job and grouping replaces this one.
        url: the Pushgateway root; None reads PUSHGATEWAY_URL. When neither is
            set, nothing is pushed.

    Returns:
        True when pushed, False when skipped or failed (logged to stderr).

    Example:
        push(monitoring_samples(summary), "monitoring", {"model_name": "m"})
    """
    base = url or os.environ.get("PUSHGATEWAY_URL", "")
    if not base:
        print("PUSHGATEWAY_URL not set, metrics not pushed", file=sys.stderr)
        return False
    path = f"/metrics/job/{urllib.parse.quote(job, safe='')}"
    for key, value in grouping.items():
        path += f"/{urllib.parse.quote(key, safe='')}/{urllib.parse.quote(str(value), safe='')}"
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=format_metrics(samples).encode("utf-8"),
        method="PUT",
        headers={"Content-Type": "text/plain; version=0.0.4"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True
    except Exception as error:  # noqa: BLE001 - never fail a step over a metric
        print(f"could not push metrics to {base}: {error}", file=sys.stderr)
        return False
