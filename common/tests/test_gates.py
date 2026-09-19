"""Tests for the two gates that decide whether a model gets promoted.

These rules are the only thing standing between a bad model and production, so
each branch gets its own test.
"""

import pytest

from ml_common.gates import evaluate_gates


def test_passes_both_gates():
    result = evaluate_gates(
        "regression", candidate={"r2": 0.80, "rmse": 1000.0}, champion={"r2": 0.78, "rmse": 1200.0}
    )
    assert result["passed"] is True
    assert result["floor_passed"] is True
    assert result["beats_champion"] is True


def test_below_floor_is_blocked_even_without_a_champion():
    result = evaluate_gates("regression", candidate={"r2": 0.10, "rmse": 9000.0}, champion=None)
    assert result["passed"] is False
    assert result["floor_passed"] is False


def test_above_floor_with_no_champion_passes():
    """First model ever: only gate one applies."""
    result = evaluate_gates("regression", candidate={"r2": 0.80, "rmse": 1000.0}, champion=None)
    assert result["passed"] is True
    assert result["beats_champion"] is None


def test_above_floor_but_worse_than_champion_is_blocked():
    result = evaluate_gates(
        "regression", candidate={"r2": 0.76, "rmse": 1500.0}, champion={"r2": 0.90, "rmse": 900.0}
    )
    assert result["passed"] is False
    assert result["floor_passed"] is True
    assert result["beats_champion"] is False


def test_exactly_at_the_floor_passes():
    """The spec says R2 >= 0.75, so 0.75 is a pass."""
    result = evaluate_gates("regression", candidate={"r2": 0.75, "rmse": 1000.0}, champion=None)
    assert result["floor_passed"] is True


def test_tying_the_champion_is_not_beating_it():
    result = evaluate_gates(
        "regression", candidate={"r2": 0.80, "rmse": 1000.0}, champion={"r2": 0.80, "rmse": 1000.0}
    )
    assert result["beats_champion"] is False
    assert result["passed"] is False


def test_classification_uses_auc_for_both_gates():
    result = evaluate_gates("classification", candidate={"auc": 0.72}, champion={"auc": 0.65})
    assert result["passed"] is True


def test_classification_below_floor_is_blocked():
    result = evaluate_gates("classification", candidate={"auc": 0.52}, champion=None)
    assert result["passed"] is False


def test_reason_names_the_gate_that_blocked():
    below_floor = evaluate_gates("regression", candidate={"r2": 0.1, "rmse": 9.0}, champion=None)
    assert "floor" in below_floor["reason"].lower()

    worse = evaluate_gates(
        "regression", candidate={"r2": 0.76, "rmse": 1500.0}, champion={"r2": 0.9, "rmse": 900.0}
    )
    assert "champion" in worse["reason"].lower()


def test_missing_metric_raises_rather_than_guessing():
    with pytest.raises(KeyError):
        evaluate_gates("regression", candidate={"mae": 100.0}, champion=None)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        evaluate_gates("clustering", candidate={"r2": 0.9}, champion=None)


def test_a_constant_predictor_cannot_pass_the_classification_floor():
    """A model that predicts one class for everything scores AUC 0.5 by definition.

    The old F1 floor let exactly such a model through: predicting the majority
    class on a 55.8%-positive target gives recall 1.0 and F1 0.719, above the
    old 0.70 bar, while its AUC was 0.500.
    """
    result = evaluate_gates("classification", candidate={"auc": 0.50}, champion=None)
    assert result["passed"] is False
    assert "floor" in result["reason"].lower()


def test_a_good_model_with_low_f1_still_passes():
    """F1 collapses on an imbalanced target at the default 0.5 threshold.

    The real classifier scores AUC 0.706 but F1 0.159 on a 25%-positive target.
    The gate must judge it on AUC, or it would block a genuinely good model.
    """
    result = evaluate_gates("classification", candidate={"auc": 0.706}, champion=None)
    assert result["passed"] is True


def test_classification_missing_auc_raises():
    """AUC is now load-bearing: evaluate must always supply it, or we stop."""
    with pytest.raises(KeyError):
        evaluate_gates("classification", candidate={"f1": 0.9}, champion=None)
