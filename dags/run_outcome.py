"""Reports how a pipeline run ended to the Pushgateway, for alerting (CN-46).

Called from DAG-level success and failure callbacks. Standard library only: it
runs inside the Airflow image, which has neither ml_common nor prometheus_client.
Best effort, like every metric push: a callback must never raise.
"""

from __future__ import annotations

import os
import urllib.request

STATUSES = ("success", "blocked", "failed", "smoke_test_failed")


def classify(task_states: dict[str, str]) -> str:
    """Decides how a run ended from the state of its tasks.

    Args:
        task_states: task id to its final state ("success", "failed",
            "skipped", "upstream_failed", ...).

    Returns:
        "smoke_test_failed" when `deploy` failed (serving did not take the new
        version; the alias was rolled back), "failed" when anything else
        failed, "blocked" when the gates stopped the model (`stop_no_deploy`
        ran), "success" otherwise.

    Example:
        classify({"evaluate": "success", "stop_no_deploy": "success",
                  "register": "skipped"})   # -> "blocked"
    """
    failed = {t for t, s in task_states.items() if s in ("failed", "upstream_failed")}
    if task_states.get("deploy") == "failed":
        return "smoke_test_failed"
    if failed:
        return "failed"
    if task_states.get("stop_no_deploy") == "success":
        return "blocked"
    return "success"


def render(pipeline: str, task_type: str, status: str, finished_at: float) -> str:
    """Renders the run's outcome in the Prometheus text format.

    Args:
        pipeline: the DAG id.
        task_type: the task the run was for.
        status: one of `STATUSES`.
        finished_at: Unix time the run ended.

    Returns:
        One `ml_pipeline_last_run_status` sample per status - 1 for the one
        that happened, 0 for the others - plus the end time. Alert rules
        match `status=~"failed|smoke_test_failed"` equal to 1.

    Example:
        render("ml_pipeline", "regression", "failed", 1.7e9)
    """
    labels = f'pipeline="{pipeline}",task_type="{task_type}"'
    lines = [
        "# HELP ml_pipeline_last_run_status 1 for how the last run ended, 0 for the others.",
        "# TYPE ml_pipeline_last_run_status gauge",
    ]
    for candidate in STATUSES:
        value = 1 if candidate == status else 0
        lines.append(f'ml_pipeline_last_run_status{{{labels},status="{candidate}"}} {value}')
    lines.append("# HELP ml_pipeline_last_run_finished_seconds Unix time the last run ended.")
    lines.append("# TYPE ml_pipeline_last_run_finished_seconds gauge")
    lines.append(f"ml_pipeline_last_run_finished_seconds{{{labels}}} {finished_at:.0f}")
    return "\n".join(lines) + "\n"


def report(context: dict) -> None:
    """DAG callback: pushes how the run ended. Never raises.

    Args:
        context: the Airflow callback context (`dag_run`, maybe `params`).

    Returns:
        None. Skipped when PUSHGATEWAY_URL is not set.

    Example:
        DAG(..., on_success_callback=report, on_failure_callback=report)
    """
    url = os.environ.get("PUSHGATEWAY_URL", "").rstrip("/")
    if not url:
        return
    try:
        dag_run = context["dag_run"]
        states = {ti.task_id: ti.state for ti in dag_run.get_task_instances()}
        # A DAG-level callback's context may lack `params`; the run's conf is
        # always there when triggered from the API.
        task_type = (
            (dag_run.conf or {}).get("task_type")
            or (context.get("params") or {}).get("task_type")
            or "unknown"
        )
        status = classify(states)
        finished = (dag_run.end_date or dag_run.start_date).timestamp()
        body = render(dag_run.dag_id, task_type, status, finished).encode("utf-8")
        target = f"{url}/metrics/job/pipeline/pipeline/{dag_run.dag_id}/task_type/{task_type}"
        request = urllib.request.Request(target, data=body, method="PUT",
                                         headers={"Content-Type": "text/plain; version=0.0.4"})
        with urllib.request.urlopen(request, timeout=10):
            pass
        print(f"reported {dag_run.dag_id} run as {status}")
    except Exception as error:  # noqa: BLE001 - a callback must never raise
        print(f"could not report the run outcome: {error}")
