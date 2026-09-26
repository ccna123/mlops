"""The model card: a short description that travels with each model version (CN-12).

It answers, for someone who never read the code: what the model is for, what
data it learned from, how good it is overall and per group, at which decision
threshold it answers (classification), which columns it may not look at, and
where it is known to be weak.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import schema

PURPOSE: dict[str, str] = {
    "regression": "Predicts the final sale price of a house, in US dollars.",
    "classification": (
        "Predicts whether a house needs renovation (condition poor or fair), "
        "from objective attributes, because sellers often leave condition blank "
        "or describe it too kindly."
    ),
}

KNOWN_LIMITATIONS: dict[str, list[str]] = {
    "regression": [
        "Trained on simulated data, not real transactions.",
        "Tree models cannot predict prices above the range they learned; a market "
        "that rises beyond it is underestimated.",
        "The zipcode column has tens of thousands of values; almost all fall into "
        "the 'rare' group and add little.",
        "Performance drift is only known once sale prices come back as ground truth.",
    ],
    "classification": [
        "Trained on simulated data, not real transactions.",
        "The label comes from the condition the seller declared, which can itself "
        "be wrong.",
        "About 25% of houses need renovation; precision is low at the recall target, "
        "so a flag means 'check this', not 'this needs work'.",
        "The decision threshold was chosen for 70% recall on the latest 20% of the "
        "train set; a shift in the market moves the recall it actually reaches.",
    ],
}


def excluded_columns(task_type: str) -> list[str]:
    """Lists the columns the model may not use as features (要件定義書 6.3).

    Args:
        task_type: "regression" or "classification".

    Returns:
        The excluded columns, in schema order.

    Example:
        excluded_columns("regression")
        # -> ["property_id", "list_price", "sale_price", "price_category"]
    """
    kept = set(schema.feature_columns(task_type))
    return [name for name in schema.COLUMNS if name not in kept]


def build_model_card(
    *,
    model_name: str,
    version: str,
    task_type: str,
    params: dict,
    test_metrics: dict,
    group_metrics: dict | None,
) -> dict:
    """Assembles the model card of one registered model version.

    Args:
        model_name: the registered model.
        version: the new version number.
        task_type: "regression" or "classification".
        params: the training run's params (estimator, dataset_version,
            split_points, data_id, seed, git_commit, image_digest,
            decision_threshold ...), as MLflow returns them (strings).
        test_metrics: the metrics on the test set, without the `test_` prefix.
        group_metrics: what evaluate logged per city and property type, or None.

    Returns:
        A JSON-friendly dict. Fields the run did not log are None, never
        guessed.

    Example:
        card = build_model_card(model_name="house_price_regressor", version="5",
                                task_type="regression", params=run.data.params,
                                test_metrics={"rmse": 150000.0, "r2": 0.81},
                                group_metrics=groups)
        card["data"]["dataset_version"]  # -> "v2"
    """
    threshold = params.get("decision_threshold")
    return {
        "model_name": model_name,
        "version": str(version),
        "task_type": task_type,
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": PURPOSE[task_type],
        "algorithm": {
            "estimator": params.get("estimator"),
            "tuned": params.get("tune_hyperparameters"),
            "decision_threshold": float(threshold) if threshold is not None else None,
        },
        "data": {
            "dataset_version": params.get("dataset_version"),
            "data_id": params.get("data_id") or params.get("fingerprint"),
            "split_points": params.get("split_points"),
            "train_rows": params.get("train_rows"),
            "sample_rows": params.get("sample_rows"),
            "seed": params.get("seed"),
        },
        "code": {
            "git_commit": params.get("git_commit"),
            "image_digest": params.get("image_digest"),
        },
        "metrics": {"test": test_metrics, "by_group": group_metrics},
        "excluded_columns": excluded_columns(task_type),
        "known_limitations": KNOWN_LIMITATIONS[task_type],
    }
