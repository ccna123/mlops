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

from ml_common import schema
from ml_common.storage import Storage, raw_key

from .runner import build_requests, send_feedback, send_predictions
from .scenarios import SCENARIOS

DEFAULT_POOL_ROWS = 20_000


def parse_args() -> argparse.Namespace:
    """Reads the command line.

    Args:
        None. Parses sys.argv.

    Returns:
        A namespace with `scenario`, `task_type`, `count`, `seed`,
        `pool_rows`, `feedback_ratio` and `dataset_version`.

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
        "--pool-rows",
        type=int,
        default=DEFAULT_POOL_ROWS,
        help="how many of the most recent raw rows to sample from",
    )
    parser.add_argument(
        "--feedback-ratio",
        type=float,
        default=1.0,
        help="fraction of served requests to report outcomes for; 0 sends none",
    )
    parser.add_argument("--dataset-version", default=os.environ.get("DATASET_VERSION", "v1"))
    return parser.parse_args()


def load_pool(storage: Storage, dataset_version: str, pool_rows: int) -> pd.DataFrame:
    """Reads the most recent raw rows to draw traffic from.

    Args:
        storage: where the raw dataset lives.
        dataset_version: which raw version to read, e.g. "v1".
        pool_rows: how many of the most recent rows, by listing_date, to keep.

    Returns:
        The tail of the dataset ordered by `listing_date`. Whether these rows
        are ones the model has seen depends on SAMPLE_ROWS: `extract` takes
        head(SAMPLE_ROWS), so with the dev setting of 200k the tail really is
        unseen, and on a full 2-million-row run nothing is. Either way the
        drift comes from the scenario, not from the choice of rows.

    Example:
        pool = load_pool(storage, "v1", 20_000)
        # -> the 20,000 most recently listed houses
    """
    frame = storage.read_parquet(raw_key(dataset_version))
    if "listing_date" in frame.columns:
        frame = frame.sort_values("listing_date", na_position="first")
    return frame.tail(pool_rows).reset_index(drop=True)


def main() -> int:
    """Sends one batch of traffic and reports the outcomes.

    Args:
        None. Takes settings from the command line, SERVING_URL (default
        http://serving:8000), and the MinIO variables Storage.from_env needs.

    Returns:
        0 on success, 1 when the pool yielded no usable rows.

    Example:
        # python -m services.agent --scenario price_inflation --count 500
        # -> pool 20000 rows
        #    sent 500 predictions to http://serving:8000
        #    reported 500 outcomes, accepted 500
    """
    args = parse_args()
    base_url = os.environ.get("SERVING_URL", "http://serving:8000").rstrip("/")

    pool = load_pool(Storage.from_env(), args.dataset_version, args.pool_rows)
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
