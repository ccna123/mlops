"""Command line for the traffic agent.

Runs one bounded batch and exits. That boundary is the point: a scenario is
only measurable if you can say "exactly these 500 requests were
price_inflation", and a process that runs forever cannot say that without
growing a control API of its own.

The always-on mode is the compose service, which loops over this same code.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
import pandas as pd

from ml_common import lineage, schema
from ml_common.datasets import ensure_manifest
from ml_common.storage import Storage, raw_key

from .runner import build_requests, select_pool, send_feedback, send_predictions
from .scenarios import SCENARIOS


def parse_args() -> argparse.Namespace:
    """Reads the command line.

    Args:
        None. Parses sys.argv.

    Returns:
        A namespace with `scenario`, `task_type`, `count`, `seed`,
        `feedback_ratio` and `dataset_version` (used only when the champion
        cannot be traced to its own).

    Example:
        # python -m services.agent --scenario price_inflation --count 500
        # -> scenario="price_inflation", count=500, feedback_ratio=1.0
    """
    parser = argparse.ArgumentParser(description="Send simulated traffic to serving.")
    parser.add_argument("--scenario", choices=SCENARIOS, default="none")
    parser.add_argument("--task-type", choices=schema.TASK_TYPES, default="regression")
    parser.add_argument("--count", type=int, default=200, help="requests to send")
    parser.add_argument("--seed", type=int, default=42, help="makes the sample reproducible")
    parser.add_argument(
        "--feedback-ratio",
        type=float,
        default=1.0,
        help="fraction of served requests to report outcomes for; 0 sends none",
    )
    parser.add_argument("--dataset-version", default=os.environ.get("DATASET_VERSION", "v1"))
    return parser.parse_args()


def champion_source(task_type: str) -> tuple[str, set] | None:
    """Traces the champion to the dataset version and train set it learned from.

    Args:
        task_type: which model's champion.

    Returns:
        `(dataset_version, property ids of its train set)`, or None when there
        is no MLflow configured, no champion, or a champion trained before
        dataset versions were logged.

    Example:
        champion_source("regression")  # -> ("v1", {"p1", "p7", ...})
    """
    if not os.environ.get("MLFLOW_TRACKING_URI"):
        return None
    from mlflow import MlflowClient

    client = MlflowClient()
    version = lineage.champion_version(client, schema.MODEL_NAMES[task_type])
    if version is None:
        return None
    params = lineage.run_params(client, version.run_id)
    dataset_version = params.get("dataset_version")
    if not dataset_version or dataset_version == "unknown":
        return None
    train = Storage.from_env().read_parquet(
        lineage.train_set_key(client, version.run_id, task_type), columns=[schema.ID_COLUMN]
    )
    return dataset_version, set(train[schema.ID_COLUMN].astype(str))


def load_pool(storage: Storage, task_type: str, fallback_version: str) -> pd.DataFrame:
    """Reads the houses the agent may send.

    Args:
        storage: where dataset versions live.
        task_type: which model the traffic is for.
        fallback_version: the dataset version to use when the champion cannot
            be traced (no champion yet): its simulation set, with nothing
            excluded.

    Returns:
        The simulation set of the champion's dataset version minus the houses
        of the champion's train set (`runner.select_pool`, CN-26).

    Example:
        pool = load_pool(storage, "regression", "v1")
        # -> about 20,000 rows listed after T2, none the champion trained on
    """
    traced = champion_source(task_type)
    dataset_version, excluded = traced if traced else (fallback_version, set())
    print(
        f"pool from {dataset_version}"
        + ("" if traced else " (no traceable champion, nothing excluded)"),
        file=sys.stderr,
    )
    manifest = ensure_manifest(storage, dataset_version)
    raw = storage.read_parquet(raw_key(dataset_version))
    return select_pool(raw, manifest["split_points"], excluded)


def main() -> int:
    """Sends one batch of traffic and reports the outcomes.

    Args:
        None. Takes settings from the command line, SERVING_URL (default
        http://serving:8000), MLFLOW_TRACKING_URI (to trace the champion), and
        the MinIO variables Storage.from_env needs.

    Returns:
        0 on success, 1 when the pool yielded no usable rows.

    Example:
        # python -m services.agent --scenario price_inflation --count 500
        # -> pool from v1
        #    pool 19873 rows
        #    sent 500 predictions to http://serving:8000
        #    reported 500 outcomes, accepted 500
    """
    args = parse_args()
    base_url = os.environ.get("SERVING_URL", "http://serving:8000").rstrip("/")

    pool = load_pool(Storage.from_env(), args.task_type, args.dataset_version)
    print(f"pool {len(pool)} rows", file=sys.stderr)

    requests = build_requests(pool, args.scenario, args.task_type, args.count, args.seed)
    if not requests:
        print("FATAL: no usable rows in the pool", file=sys.stderr)
        return 1

    with httpx.Client(timeout=30.0) as client:

        def post(url: str, json: dict) -> dict:
            response = client.post(url, json=json)
            response.raise_for_status()
            return response.json()

        served = send_predictions(post, base_url, args.task_type, requests)
        print(f"sent {len(served)} predictions to {base_url}", file=sys.stderr)

        reported = served[: int(len(served) * args.feedback_ratio)]
        result = send_feedback(post, base_url, args.task_type, reported)
        print(
            f"reported {len(reported)} outcomes, accepted {result['accepted']}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
