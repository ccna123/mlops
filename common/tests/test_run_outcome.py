"""The DAG's run-outcome reporting. It lives in dags/ (stdlib only), loaded by path."""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "dags" / "run_outcome.py"
_spec = importlib.util.spec_from_file_location("run_outcome", _PATH)
run_outcome = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_outcome)


def test_a_failed_deploy_is_a_smoke_test_failure():
    states = {"register": "success", "deploy": "failed"}
    assert run_outcome.classify(states) == "smoke_test_failed"


def test_any_other_failure_is_failed():
    assert run_outcome.classify({"train": "failed", "evaluate": "upstream_failed"}) == "failed"


def test_blocked_by_the_gates_is_not_a_failure():
    states = {"evaluate": "success", "stop_no_deploy": "success", "register": "skipped"}
    assert run_outcome.classify(states) == "blocked"


def test_a_deployed_model_is_success():
    states = {"register": "success", "deploy": "success", "stop_no_deploy": "skipped"}
    assert run_outcome.classify(states) == "success"


def test_render_sets_only_the_status_that_happened():
    text = run_outcome.render("ml_pipeline", "regression", "failed", 1_700_000_000)
    assert 'status="failed"} 1' in text
    assert 'status="success"} 0' in text
    assert "ml_pipeline_last_run_finished_seconds" in text


def test_report_without_a_url_does_nothing(monkeypatch):
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    run_outcome.report({})  # must not raise


def test_report_never_raises_on_a_broken_context(monkeypatch):
    monkeypatch.setenv("PUSHGATEWAY_URL", "http://127.0.0.1:9")
    run_outcome.report({"dag_run": None})
