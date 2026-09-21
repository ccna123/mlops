import threading
import time

import pytest
from fastapi.testclient import TestClient

import services.api.routes.health as health_module
from services.api.app import create_app
from services.api.routes.health import build_health


def _client(probes: dict) -> TestClient:
    return TestClient(create_app(probes=probes))


def test_health_is_ok_when_every_dependency_answers():
    client = _client({"airflow": lambda: True, "mlflow": lambda: True})
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["services"] == {"airflow": "ok", "mlflow": "ok"}


def test_health_is_degraded_when_one_dependency_is_down():
    client = _client({"airflow": lambda: True, "mlflow": lambda: False})
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["services"]["mlflow"] == "down"


def test_a_probe_that_raises_counts_as_down_not_a_crash():
    def explode():
        raise RuntimeError("connection refused")

    client = _client({"airflow": explode})
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["services"]["airflow"] == "down"


def test_health_always_returns_200_even_when_everything_is_down():
    client = _client({"airflow": lambda: False, "mlflow": lambda: False})
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


# --- bounded latency: /health must answer even when a dependency hangs ------

HANG_SECONDS = 3.0  # far past every deadline below; the fakes stop early via `release`
DEADLINE = 0.2
ANSWER_BOUND = 1.5  # what "returns promptly" means when DEADLINE is 0.2


class HangingProbe:
    """A probe that blocks until released (or HANG_SECONDS pass), counting its starts."""

    def __init__(self):
        self.starts = 0
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self.starts += 1
        self.release.wait(HANG_SECONDS)
        return True


class SlowProbe:
    """A probe that takes `seconds` and then answers True."""

    def __init__(self, seconds):
        self.seconds = seconds

    def __call__(self):
        time.sleep(self.seconds)
        return True


@pytest.fixture
def hanging():
    """Hanging probes to create; every one is released when the test ends."""
    created: list[HangingProbe] = []

    def make():
        probe = HangingProbe()
        created.append(probe)
        return probe

    yield make
    for probe in created:
        probe.release.set()


def _timed(probes, **kwargs):
    started = time.monotonic()
    result = build_health(probes, **kwargs)
    return result, time.monotonic() - started


def _wait_until_probe_thread_ends(name, patience=3.0):
    """Blocks until no probe thread called `name` is alive (its guard entry is gone by then)."""
    give_up = time.monotonic() + patience
    while time.monotonic() < give_up:
        alive = [t for t in threading.enumerate() if t.name == f"health-probe-{name}"]
        if not any(t.is_alive() for t in alive):
            return
        time.sleep(0.01)
    raise AssertionError(f"probe thread {name!r} did not end")


def test_a_hung_probe_is_down_and_does_not_hold_up_the_others(hanging):
    stuck = hanging()

    result, elapsed = _timed(
        {"airflow": lambda: True, "mlflow": stuck, "minio": lambda: True}, timeout=DEADLINE
    )

    assert result["services"] == {"airflow": "ok", "mlflow": "down", "minio": "ok"}
    assert result["status"] == "degraded"
    assert elapsed < ANSWER_BOUND


def test_every_probe_hanging_still_answers_within_the_bound(hanging):
    probes = {name: hanging() for name in ("airflow", "mlflow", "minio", "serving", "postgres")}

    result, elapsed = _timed(probes, timeout=DEADLINE)

    assert set(result["services"].values()) == {"down"}
    assert elapsed < ANSWER_BOUND


def test_probes_run_concurrently_not_one_after_another():
    # Five probes of 0.3 s each: 1.5 s in a row, about 0.3 s side by side.
    probes = {f"dep{i}": SlowProbe(0.3) for i in range(5)}

    result, elapsed = _timed(probes, timeout=2.0)

    assert set(result["services"].values()) == {"ok"}
    assert elapsed < 0.9


def test_a_probe_that_finishes_just_inside_the_deadline_counts_as_ok():
    result, _ = _timed({"airflow": SlowProbe(0.05)}, timeout=1.0)

    assert result["services"] == {"airflow": "ok"}


def test_a_probe_still_running_from_the_previous_call_is_not_started_again(hanging):
    stuck = hanging()
    probes = {"mlflow": stuck, "airflow": lambda: True}

    first = build_health(probes, timeout=DEADLINE)
    second, elapsed = _timed(probes, timeout=DEADLINE)

    assert first["services"]["mlflow"] == "down"
    assert second["services"] == {"mlflow": "down", "airflow": "ok"}
    assert stuck.starts == 1, "a second thread was piled on top of the stuck one"
    # The second call waited for the running probe until its own deadline
    # (it used to report "down" at once, which also hid a merely slow probe).
    assert elapsed < ANSWER_BOUND


def test_many_polls_while_a_probe_is_stuck_leave_exactly_one_thread_behind(hanging):
    stuck = hanging()

    for _ in range(10):
        build_health({"mlflow": stuck}, timeout=0.05)

    assert stuck.starts == 1


def test_once_the_stuck_probe_finishes_a_later_call_runs_it_again(hanging):
    stuck = hanging()
    probes = {"mlflow": stuck}
    assert build_health(probes, timeout=DEADLINE)["services"]["mlflow"] == "down"

    stuck.release.set()
    # A call made in the instant between the probe finishing and its guard entry
    # being cleared would (correctly) read that finished probe's result instead
    # of starting one, so wait until the thread is gone first.
    _wait_until_probe_thread_ends("mlflow")
    later = build_health(probes, timeout=DEADLINE)

    assert later["services"]["mlflow"] == "ok"
    assert stuck.starts == 2


def test_the_guard_is_per_probe_so_separate_apps_do_not_affect_each_other(hanging):
    # Two create_app() instances build their own probe callables, so the stuck
    # probe of one cannot make the same-named probe of the other read "down".
    stuck = hanging()
    build_health({"mlflow": stuck}, timeout=DEADLINE)

    other_app_result = build_health({"mlflow": lambda: True}, timeout=DEADLINE)

    assert other_app_result["services"] == {"mlflow": "ok"}


def test_a_probe_that_raises_is_down_and_the_others_are_unaffected():
    def explode():
        raise RuntimeError("connection refused")

    result = build_health({"a": lambda: True, "b": explode, "c": lambda: True}, timeout=1.0)

    assert result["services"] == {"a": "ok", "b": "down", "c": "ok"}


def test_a_probe_that_returns_false_is_down():
    result = build_health({"a": lambda: False}, timeout=1.0)

    assert result["services"] == {"a": "down"}


def test_the_result_keeps_its_shape_and_the_probe_order():
    result = build_health({"z": lambda: True, "a": lambda: True}, timeout=1.0)

    assert set(result) == {"status", "services"}
    assert list(result["services"]) == ["z", "a"]
    assert result["status"] == "ok"


def test_the_route_answers_promptly_when_a_dependency_hangs(monkeypatch, hanging):
    monkeypatch.setattr(health_module, "PROBE_TIMEOUT_S", DEADLINE)
    client = _client({"mlflow": hanging(), "airflow": lambda: True})

    started = time.monotonic()
    response = client.get("/api/health")
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert response.json()["services"] == {"mlflow": "down", "airflow": "ok"}
    assert elapsed < ANSWER_BOUND


def test_the_default_deadline_is_five_seconds():
    assert health_module.PROBE_TIMEOUT_S == 5.0


def test_a_stuck_probe_runs_on_a_daemon_thread_so_it_cannot_block_shutdown(hanging):
    stuck = hanging()

    build_health({"mlflow": stuck}, timeout=DEADLINE)

    (thread,) = [t for t in threading.enumerate() if t.name == "health-probe-mlflow"]
    assert thread.daemon


def test_a_raising_probe_is_contained_and_leaves_no_unhandled_thread_exception(monkeypatch):
    # An escaping exception would print a traceback to stderr on every poll.
    escaped = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args.exc_value))

    def explode():
        raise RuntimeError("connection refused")

    result = build_health({"a": explode}, timeout=1.0)
    time.sleep(0.1)

    assert result["services"] == {"a": "down"}
    assert escaped == []


# --- two overlapping /health requests share the one probe thread ------------
#
# A probe still running from the previous call is usually just slow, not stuck.
# The second call must wait for THAT probe (never start another) and report what
# it really returned, or "down" only if it misses the second call's own deadline.


class CountingSlowProbe:
    """A probe that takes `seconds`, answers `answer`, and counts how often it started."""

    def __init__(self, seconds, answer=True):
        self.seconds = seconds
        self.answer = answer
        self.starts = 0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self.starts += 1
        time.sleep(self.seconds)
        return self.answer


def _overlapping(probes, timeout, gap=0.2):
    """Runs two build_health calls `gap` seconds apart, each on its own thread.

    Returns:
        ((first result, first seconds), (second result, second seconds)).
    """
    outcomes: dict[str, tuple[dict, float]] = {}

    def call(label):
        outcomes[label] = _timed(probes, timeout=timeout)

    first = threading.Thread(target=call, args=("first",))
    second = threading.Thread(target=call, args=("second",))
    first.start()
    time.sleep(gap)
    second.start()
    first.join(10)
    second.join(10)
    return outcomes["first"], outcomes["second"]


def test_two_overlapping_calls_both_report_a_slow_but_healthy_probe_ok():
    probe = CountingSlowProbe(1.0)

    (first, _), (second, second_seconds) = _overlapping({"mlflow": probe}, timeout=3.0)

    assert first["services"] == {"mlflow": "ok"}
    assert second["services"] == {"mlflow": "ok"}
    assert probe.starts == 1, "the second call started its own probe instead of waiting"
    assert second["status"] == "ok"
    # It waited for the running probe (about 0.8 s left), not for the full deadline.
    assert second_seconds < 2.0


def test_the_overlapping_call_reports_the_real_result_when_the_probe_says_down():
    probe = CountingSlowProbe(0.6, answer=False)

    (first, _), (second, _) = _overlapping({"mlflow": probe}, timeout=3.0, gap=0.1)

    assert first["services"] == {"mlflow": "down"}
    assert second["services"] == {"mlflow": "down"}
    assert probe.starts == 1


def test_overlapping_calls_on_a_probe_that_never_finishes_are_both_down_within_the_deadline(
    hanging,
):
    stuck = hanging()

    (first, first_seconds), (second, second_seconds) = _overlapping(
        {"mlflow": stuck, "airflow": lambda: True}, timeout=DEADLINE, gap=0.1
    )

    assert first["services"] == {"mlflow": "down", "airflow": "ok"}
    assert second["services"] == {"mlflow": "down", "airflow": "ok"}
    assert stuck.starts == 1
    assert first_seconds < ANSWER_BOUND
    # The second call waits out ITS OWN deadline, counted from when it began.
    assert DEADLINE * 0.8 < second_seconds < ANSWER_BOUND


def test_after_the_shared_probe_is_released_a_later_call_starts_a_new_one(hanging):
    stuck = hanging()
    probes = {"mlflow": stuck}
    _overlapping(probes, timeout=DEADLINE, gap=0.05)
    assert stuck.starts == 1

    stuck.release.set()
    _wait_until_probe_thread_ends("mlflow")
    later = build_health(probes, timeout=DEADLINE)

    assert later["services"]["mlflow"] == "ok"
    assert stuck.starts == 2


def test_a_probe_whose_thread_cannot_start_is_down_and_leaves_no_stale_entry(monkeypatch):
    calls = []
    probe = CountingSlowProbe(0.0)

    def refuse(self):
        calls.append(self.name)
        raise RuntimeError("can't start new thread")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", refuse)
        result = build_health({"mlflow": probe, "airflow": lambda: True}, timeout=DEADLINE)

    assert result["services"] == {"mlflow": "down", "airflow": "down"}
    assert len(calls) == 2
    assert probe.starts == 0
    # Nothing was left behind saying "still running": the next call runs it.
    assert build_health({"mlflow": probe}, timeout=1.0)["services"] == {"mlflow": "ok"}
    assert probe.starts == 1
