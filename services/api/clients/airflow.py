"""Talks to Airflow's REST API and hands back shapes the routes can use.

Airflow's payloads carry far more than a dashboard needs and use names from
its own domain. Normalising here means the routes - and the frontend behind
them - never learn what a `dag_run_id` or an `execution_date` is, so
swapping Airflow for MWAA later changes this file and nothing else.

Basic auth is used on every call, which requires
AIRFLOW__API__AUTH_BACKENDS to include basic_auth. Airflow 2.10 ships only
the session backend and answers 401 without saying why.
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 30.0


class AirflowClient:
    """A thin, normalising wrapper over the Airflow REST API.

    Example:
        client = AirflowClient("http://airflow-webserver:8080/api/v1", "admin", "admin")
        client.trigger_run("ml_pipeline", {"task_type": "regression"})
        # -> {"run_id": "manual__2026-09-20T...", "dag_id": "ml_pipeline",
        #     "state": "queued"}
    """

    def __init__(self, base_url: str, username: str, password: str, http=None):
        """Records where Airflow is and how to authenticate to it.

        Args:
            base_url: the API root, e.g. "http://airflow-webserver:8080/api/v1".
            username: Airflow user with permission to trigger DAGs.
            password: that user's password.
            http: something with `.request(method, url, **kwargs)` returning a
                response. None builds a real httpx client. Injected so the
                tests need no Airflow.
        """
        self._base = base_url.rstrip("/")
        self._auth = (username, password)
        self._http = http if http is not None else httpx.Client(timeout=DEFAULT_TIMEOUT)

    def _call(self, method: str, path: str, **kwargs) -> dict:
        """Makes one authenticated request and returns the decoded body.

        Args:
            method: "GET" or "POST".
            path: path below the API root, starting with "/".
            **kwargs: passed through to the HTTP client.

        Returns:
            The decoded JSON body.

        Raises:
            Exception: whatever the HTTP client raises for a non-2xx status.
                Errors are not swallowed here - a route that cannot reach
                Airflow must say so rather than return an empty list that
                looks like "nothing has run yet".

        Example:
            self._call("GET", "/dags/ml_pipeline/dagRuns", params={"limit": 5})
        """
        response = self._http.request(method, f"{self._base}{path}", auth=self._auth, **kwargs)
        response.raise_for_status()
        return response.json()

    def trigger_run(self, dag_id: str, conf: dict) -> dict:
        """Starts a DAG run and returns its identifier.

        Args:
            dag_id: the DAG to start, e.g. "ml_pipeline".
            conf: the run configuration, which becomes `params` inside the DAG.

        Returns:
            `run_id`, `dag_id` and `state`. The run has only been QUEUED -
            it has not finished, and on this pipeline it will take minutes.

        Example:
            trigger_run("ml_pipeline", {"task_type": "regression", "sample_rows": 1000})
            # -> {"run_id": "manual__2026-09-20T10:00:00+00:00",
            #     "dag_id": "ml_pipeline", "state": "queued"}
        """
        body = self._call("POST", f"/dags/{dag_id}/dagRuns", json={"conf": conf})
        return {"run_id": body["dag_run_id"], "dag_id": dag_id, "state": body["state"]}

    def list_runs(self, dag_id: str, limit: int) -> list[dict]:
        """Lists recent runs, newest first.

        Args:
            dag_id: the DAG to list.
            limit: how many runs to return.

        Returns:
            One dict per run with `run_id`, `state`, `task_type`, `started_at`
            and `ended_at`. `task_type` comes from the run's conf and is None
            for a run triggered from the Airflow UI without one. `ended_at` is
            None while the run is still going.

        Example:
            list_runs("ml_pipeline", limit=5)
            # -> [{"run_id": "manual__...", "state": "success",
            #      "task_type": "regression", "started_at": "...",
            #      "ended_at": "..."}]
        """
        # start_date is when the run actually started; execution_date is its
        # logical schedule slot. They track together for manual runs but
        # diverge for scheduled/backfilled ones, so sort by start_date.
        body = self._call(
            "GET",
            f"/dags/{dag_id}/dagRuns",
            params={"limit": limit, "order_by": "-start_date"},
        )
        return [
            {
                "run_id": run["dag_run_id"],
                "state": run["state"],
                "task_type": (run.get("conf") or {}).get("task_type"),
                "started_at": run.get("start_date"),
                "ended_at": run.get("end_date"),
            }
            for run in body.get("dag_runs", [])
        ]

    def get_run(self, dag_id: str, run_id: str) -> dict:
        """Reads one run together with the state of each of its tasks.

        Args:
            dag_id: the DAG the run belongs to.
            run_id: the run identifier.

        Returns:
            `run_id`, `state`, and `tasks` - one entry per task with
            `task_id`, `state`, `try_number` and `duration` (None while the
            task is still running).

        Raises:
            Exception: when the run does not exist. Returning an empty task
                list instead would look like a run that did nothing.

        Example:
            get_run("ml_pipeline", "manual__2026-09-20T10:00:00+00:00")
            # -> {"run_id": "...", "state": "running",
            #     "tasks": [{"task_id": "extract", "state": "success", ...}]}
        """
        run = self._call("GET", f"/dags/{dag_id}/dagRuns/{run_id}")
        instances = self._call("GET", f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances")
        return {
            "run_id": run["dag_run_id"],
            "state": run["state"],
            "tasks": [
                {
                    "task_id": task["task_id"],
                    "state": task["state"],
                    "try_number": task.get("try_number"),
                    "duration": task.get("duration"),
                }
                for task in instances.get("task_instances", [])
            ],
        }

    def get_logs(self, dag_id: str, run_id: str, task_id: str, try_number: int) -> str:
        """Fetches the log of one task attempt.

        Args:
            dag_id: the DAG the run belongs to.
            run_id: the run identifier.
            task_id: which task's log to read.
            try_number: which attempt; Airflow numbers them from 1.

        Returns:
            The log as one block of text. Splitting and filtering happen in
            the route, so this stays a transport concern.

        Raises:
            KeyError: when Airflow's response has no "content" field. Left
                to propagate rather than papered over with a default - an
                empty string here would be indistinguishable from a task
                that genuinely logged nothing.

        Example:
            get_logs("ml_pipeline", "manual__...", "extract", 1)
            # -> "[2026-09-20 10:00:01] INFO - raw=raw/v1/data.parquet ..."
        """
        body = self._call(
            "GET",
            f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}/logs/{try_number}",
        )
        return body["content"]
