"""The two gates that decide whether a trained model may be promoted.

Gate one blocks junk on an absolute threshold. Gate two blocks a model that is
merely adequate from replacing a better one already in production — both
measured on the same test split, which is why that split has a fixed seed.

Classification is judged on AUC, not F1. F1 depends on both the decision
threshold and the class balance, and it failed in both directions on real data:
a constant predictor scored F1 0.719 on a 55.8%-positive target (above the old
0.70 bar) while its AUC was 0.500, and a genuine model scored F1 0.159 on a
25%-positive target while its AUC was 0.706. AUC is threshold-independent, and
any constant predictor scores exactly 0.5 by construction.
"""

from __future__ import annotations

from . import schema

FLOOR: dict[str, tuple[str, float]] = {
    "regression": ("r2", 0.75),
    "classification": ("auc", 0.55),
}

COMPARISON: dict[str, tuple[str, str]] = {
    "regression": ("rmse", "lower"),
    "classification": ("auc", "higher"),
}


def _is_better(candidate_value: float, champion_value: float, direction: str) -> bool:
    """Compares two values of the same metric.

    Args:
        candidate_value: the challenger's score.
        champion_value: the incumbent's score on the same test split.
        direction: "lower" when a smaller number is better (rmse), "higher"
            otherwise (auc).

    Returns:
        True only on a strict improvement. A tie is not an improvement: the
        incumbent keeps its place.

    Example:
        _is_better(0.91, 0.88, "higher")    # -> True, auc went up
        _is_better(48_000, 52_000, "lower") # -> True, rmse came down
        _is_better(0.88, 0.88, "higher")    # -> False, a tie loses
    """
    if direction == "lower":
        return candidate_value < champion_value
    return candidate_value > champion_value


def evaluate_gates(task_type: str, candidate: dict, champion: dict | None) -> dict:
    """Decides whether a candidate model may take the champion alias.

    Args:
        task_type: "regression" or "classification".
        candidate: metrics of the model just trained.
        champion: metrics of the current champion on the SAME test split, or
            None when no model has been promoted yet.

    Returns:
        A dict with `passed`, `floor_passed`, `beats_champion` (None when there
        is no champion to compare against) and a human-readable `reason`.

    Raises:
        ValueError: when task_type is not one of `schema.TASK_TYPES`.
        KeyError: when a metric a gate needs is absent. Guessing here would
            silently promote a model nobody measured.

    Example:
        # First ever run — no champion to beat, the floor decides alone:
        evaluate_gates("regression", {"r2": 0.95, "rmse": 41_000}, None)
        # -> {"passed": True, "floor_passed": True, "beats_champion": None,
        #     "reason": "passed the floor (r2=0.9500); no champion yet"}

        # Good enough on its own, but not better than what is live:
        evaluate_gates("regression", {"r2": 0.94, "rmse": 45_000},
                       {"r2": 0.95, "rmse": 41_000})
        # -> {"passed": False, ..., "beats_champion": False}

        # Junk, blocked before the champion is even consulted:
        evaluate_gates("classification", {"auc": 0.50}, None)
        # -> {"passed": False, "floor_passed": False, "beats_champion": None}
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    floor_metric, floor_value = FLOOR[task_type]
    candidate_floor = candidate[floor_metric]
    floor_passed = candidate_floor >= floor_value

    if not floor_passed:
        return {
            "passed": False,
            "floor_passed": False,
            "beats_champion": None,
            "reason": (
                f"below the floor: {floor_metric}={candidate_floor:.4f} "
                f"< {floor_value} required"
            ),
        }

    if champion is None:
        return {
            "passed": True,
            "floor_passed": True,
            "beats_champion": None,
            "reason": f"passed the floor ({floor_metric}={candidate_floor:.4f}); no champion yet",
        }

    compare_metric, direction = COMPARISON[task_type]
    candidate_value = candidate[compare_metric]
    champion_value = champion[compare_metric]
    beats_champion = _is_better(candidate_value, champion_value, direction)

    if not beats_champion:
        return {
            "passed": False,
            "floor_passed": True,
            "beats_champion": False,
            "reason": (
                f"does not beat the champion: {compare_metric}={candidate_value:.4f} "
                f"vs {champion_value:.4f} ({direction} is better)"
            ),
        }

    return {
        "passed": True,
        "floor_passed": True,
        "beats_champion": True,
        "reason": (
            f"passed the floor and beat the champion: {compare_metric}="
            f"{candidate_value:.4f} vs {champion_value:.4f}"
        ),
    }
