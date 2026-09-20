"""The agent's core: turn real rows into traffic, then report what happened.

Kept free of HTTP clients and of argument parsing so the whole thing can be
tested by passing in a function that records calls. The CLI in __main__.py
supplies a real one.

Predictions and feedback are two separate calls on purpose. In production
nobody knows what a house sold for at the moment they ask what it is worth,
and splitting the two here keeps that delay visible instead of pretending
the answer arrives with the question.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from ml_common import schema
from ml_common.targets import derive_target

from .scenarios import adjust_truth, apply_scenario


def build_requests(
    pool: pd.DataFrame,
    scenario: str,
    task_type: str,
    count: int,
    seed: int,
) -> list[dict]:
    """Samples real rows and turns them into requests with known outcomes.

    Args:
        pool: rows from the raw dataset, still unparsed.
        scenario: one of `scenarios.SCENARIOS`.
        task_type: "regression" or "classification".
        count: how many requests to build. A pool smaller than this is
            sampled with replacement, so a small pool still produces traffic.
        seed: makes the sample reproducible, so a scenario can be re-run.

    Returns:
        A list of {"record": dict, "truth": value}. The record is what gets
        POSTed - raw, with the target column removed but leakage columns left
        in, because a real caller would send those and the Pipeline's
        SelectColumns is what strips them. Rows whose true outcome cannot be
        read are dropped rather than guessed, so the list may be shorter than
        `count`.

    Example:
        build_requests(pool, "price_inflation", "regression", count=500, seed=42)
        # -> 500 records with list_price multiplied by 1.2, each paired with
        #    the price the house really sold for - unchanged. list_price is
        #    not a regression feature, so the model never sees the inflation
        #    either; this scenario is a structural no-op for regression.
    """
    if len(pool) == 0:
        return []

    target = schema.target_column(task_type)
    sample = pool.sample(n=count, replace=len(pool) < count, random_state=seed)
    truths = derive_target(sample, task_type)

    requests: list[dict] = []
    for (_, row), truth in zip(sample.iterrows(), truths, strict=True):
        if truth is None or pd.isna(truth):
            continue
        record = {k: v for k, v in row.to_dict().items() if k != target}
        requests.append(
            {
                "record": apply_scenario(record, scenario),
                "truth": adjust_truth(truth, scenario, task_type),
            }
        )
    return requests


def send_predictions(
    post,
    base_url: str,
    task_type: str,
    requests: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """POSTs each record to /predict and keeps the outcome aside for later.

    Args:
        post: a callable taking (url, json=...) and returning the decoded
            response body. Injected so tests need no server.
        base_url: serving's root, e.g. "http://serving:8000".
        task_type: "regression" or "classification".
        requests: what `build_requests` produced.
        now: the moment to stamp as the prediction day. None reads the clock.

    Returns:
        One dict per served request, carrying `request_id`, `predicted_on`
        and `actual`. `predicted_on` is recorded HERE rather than read back
        from serving: the ground-truth files are partitioned by the day of
        the prediction so they line up with the inference log, and the agent
        is the only party that already knows that day.

    Example:
        served = send_predictions(post, "http://serving:8000", "regression", reqs)
        # -> [{"request_id": "3f0a...", "predicted_on": "2026-09-20",
        #      "actual": 420000.0}, ...]
    """
    moment = datetime.now(UTC) if now is None else now
    day = moment.date().isoformat()

    served: list[dict] = []
    for item in requests:
        body = post(f"{base_url}/predict/{task_type}", json=item["record"])
        served.append(
            {
                "request_id": body["request_id"],
                "predicted_on": day,
                "actual": item["truth"],
            }
        )
    return served


def send_feedback(post, base_url: str, task_type: str, outcomes: list[dict]) -> dict:
    """Reports the real outcomes back to serving as one batch.

    Args:
        post: a callable taking (url, json=...) and returning the decoded body.
        base_url: serving's root.
        task_type: "regression" or "classification".
        outcomes: what `send_predictions` returned, or a subset of it.

    Returns:
        Serving's response. An empty list makes no call at all and returns
        {"accepted": 0}, so "there is nothing to report" costs nothing and
        does not write an empty file.

    Example:
        send_feedback(post, "http://serving:8000", "regression", served)
        # -> {"accepted": 500, "key": "ground-truth/.../part-1a2b3c4d.parquet"}
        # One request, one parquet file - not 500 tiny ones.
    """
    if not outcomes:
        return {"accepted": 0}

    payload = {
        "outcomes": [
            {
                "request_id": item["request_id"],
                "predicted_on": item["predicted_on"],
                "actual": item["actual"],
            }
            for item in outcomes
        ]
    }
    return post(f"{base_url}/feedback/{task_type}", json=payload)
