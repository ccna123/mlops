"""Feedback data stage: build a new dataset version from served traffic (CN-42).

Its own container because it reads and rewrites the whole source dataset
version, which is not the orchestrator's or the API's memory to spend. All the
rules live in `ml_common.feedback`; this is the thin shell around them.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from mlflow import MlflowClient

from ml_common import lineage
from ml_common.datasets import DatasetVersionExistsError
from ml_common.feedback import NotEnoughFeedbackError, build_feedback_dataset, default_period
from ml_common.stageio import emit_result
from ml_common.storage import Storage


def champion_dataset_version(model_name: str) -> str:
    """Finds the dataset version the current champion learned from.

    Args:
        model_name: the registered model.

    Returns:
        The `dataset_version` its training run logged.

    Raises:
        ValueError: when there is no champion, or its run did not log one
            (trained before dataset versions were logged): the operator must
            then name the source version.

    Example:
        champion_dataset_version("house_price_regressor")  # -> "v1"
    """
    client = MlflowClient()
    version = lineage.champion_version(client, model_name)
    if version is None:
        raise ValueError(f"{model_name} has no champion; name the source dataset version")
    value = lineage.run_params(client, version.run_id).get("dataset_version")
    if not value or value == "unknown":
        raise ValueError("the champion did not log its dataset version; name the source")
    return value


def _moment(name: str) -> datetime | None:
    """Reads an optional ISO timestamp from the environment.

    Args:
        name: the variable name.

    Returns:
        The timezone-aware datetime, or None when unset or empty.

    Example:
        # PERIOD_START="2026-09-01T00:00:00+00:00" -> datetime(2026, 9, 1, tzinfo=UTC)
    """
    value = os.environ.get(name, "").strip()
    return datetime.fromisoformat(value) if value else None


def main() -> int:
    """Builds the feedback dataset version and reports what went into it.

    Args:
        None. Reads TASK_TYPE, MODEL_NAME, NEW_VERSION, optional SOURCE_VERSION
        (default: the champion's dataset version), PERIOD_START and PERIOD_END
        (default: the last 30 days), MLFLOW_TRACKING_URI and the MinIO
        variables `Storage.from_env` needs.

    Returns:
        0 when the version was written; 1 when it was refused (name taken, too
        little feedback, no source to extend), with the reason on stderr and in
        the stage result, so the run fails visibly rather than silently.
    """
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    new_version = os.environ["NEW_VERSION"]
    default_start, default_end = default_period()
    start = _moment("PERIOD_START") or default_start
    end = _moment("PERIOD_END") or default_end
    storage = Storage.from_env()
    try:
        source_version = (
            os.environ.get("SOURCE_VERSION", "").strip() or champion_dataset_version(model_name)
        )
        manifest = build_feedback_dataset(
            storage,
            task_type=task_type,
            model_name=model_name,
            source_version=source_version,
            start=start,
            end=end,
            new_version=new_version,
        )
    except (DatasetVersionExistsError, NotEnoughFeedbackError, ValueError) as error:
        print(f"FATAL: {error}", file=sys.stderr)
        emit_result({"ok": False, "reason": str(error)})
        return 1
    print(f"wrote {new_version}: {manifest['lineage']}", file=sys.stderr)
    emit_result({"ok": True, "dataset_version": new_version, "lineage": manifest["lineage"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
