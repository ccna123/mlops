"""Tests for the inference log buffer.

The buffer holds prediction records in memory and hands them off in batches.
Writing one object per request would fill MinIO with thousands of tiny files
and make the monitoring DAG crawl.
"""

import pytest

from ml_common.inference_log import InferenceLogBuffer


class FakeClock:
    """A clock the test moves by hand, so no test ever sleeps."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _record(index: int) -> dict:
    return {"request_id": f"r{index}", "prediction": float(index)}


def test_a_fresh_buffer_does_not_need_flushing():
    buffer = InferenceLogBuffer(clock=FakeClock())
    assert buffer.should_flush() is False


def test_reaching_flush_size_triggers_a_flush():
    buffer = InferenceLogBuffer(flush_size=3, clock=FakeClock())
    for index in range(2):
        buffer.add(_record(index))
    assert buffer.should_flush() is False
    buffer.add(_record(2))
    assert buffer.should_flush() is True


def test_age_triggers_a_flush_even_when_nearly_empty():
    clock = FakeClock()
    buffer = InferenceLogBuffer(flush_size=500, flush_seconds=30.0, clock=clock)
    buffer.add(_record(0))
    assert buffer.should_flush() is False
    clock.advance(31.0)
    assert buffer.should_flush() is True


def test_an_empty_buffer_never_flushes_no_matter_how_old():
    """Flushing nothing would write an empty file every 30 seconds forever."""
    clock = FakeClock()
    buffer = InferenceLogBuffer(clock=clock)
    clock.advance(600.0)
    assert buffer.should_flush() is False


def test_take_returns_everything_and_empties_the_buffer():
    buffer = InferenceLogBuffer(clock=FakeClock())
    buffer.add(_record(0))
    buffer.add(_record(1))
    taken = buffer.take()
    assert [item["request_id"] for item in taken] == ["r0", "r1"]
    assert buffer.stats()["buffered"] == 0


def test_take_resets_the_age_timer():
    clock = FakeClock()
    buffer = InferenceLogBuffer(flush_seconds=30.0, clock=clock)
    buffer.add(_record(0))
    clock.advance(31.0)
    buffer.take()
    buffer.add(_record(1))
    assert buffer.should_flush() is False


def test_give_back_puts_failed_records_at_the_front():
    """A failed flush must not reorder records behind ones that arrived later."""
    buffer = InferenceLogBuffer(clock=FakeClock())
    buffer.add(_record(9))
    buffer.give_back([_record(0), _record(1)])
    assert [item["request_id"] for item in buffer.take()] == ["r0", "r1", "r9"]


def test_overflow_drops_the_oldest_and_counts_it():
    buffer = InferenceLogBuffer(flush_size=3, max_size=3, clock=FakeClock())
    for index in range(5):
        buffer.add(_record(index))
    assert [item["request_id"] for item in buffer.take()] == ["r2", "r3", "r4"]
    assert buffer.stats()["dropped"] == 2


def test_give_back_beyond_the_cap_also_drops_oldest():
    """MinIO down for a long stretch must not grow the buffer without bound."""
    buffer = InferenceLogBuffer(flush_size=3, max_size=3, clock=FakeClock())
    buffer.add(_record(8))
    buffer.add(_record(9))
    buffer.give_back([_record(0), _record(1), _record(2)])
    assert buffer.stats()["buffered"] == 3
    assert buffer.stats()["dropped"] == 2


def test_dropped_count_survives_take():
    """/health reports this number, so it must not reset when a flush succeeds."""
    buffer = InferenceLogBuffer(flush_size=2, max_size=2, clock=FakeClock())
    for index in range(4):
        buffer.add(_record(index))
    buffer.take()
    assert buffer.stats()["dropped"] == 2


def test_stats_is_json_serializable():
    import json

    buffer = InferenceLogBuffer(clock=FakeClock())
    buffer.add(_record(0))
    json.dumps(buffer.stats())


def test_flush_size_must_be_at_most_max_size():
    with pytest.raises(ValueError, match="flush_size"):
        InferenceLogBuffer(flush_size=10, max_size=5)


def test_concurrent_adds_and_takes_lose_nothing():
    """Serving adds from request threads while the flusher takes from another.

    take() copies then clears; without a lock, a record added between those two
    steps is cleared without ever being handed out.
    """
    import threading

    buffer = InferenceLogBuffer(flush_size=5000, max_size=5000, clock=FakeClock())
    per_thread = 2000
    thread_count = 4
    taken: list[dict] = []
    stop = threading.Event()

    def producer(offset: int) -> None:
        for index in range(per_thread):
            buffer.add(_record(offset + index))

    def consumer() -> None:
        while not stop.is_set():
            taken.extend(buffer.take())

    consumer_thread = threading.Thread(target=consumer)
    consumer_thread.start()
    producers = [
        threading.Thread(target=producer, args=(n * per_thread,)) for n in range(thread_count)
    ]
    for thread in producers:
        thread.start()
    for thread in producers:
        thread.join()
    stop.set()
    consumer_thread.join()
    taken.extend(buffer.take())

    assert buffer.stats()["dropped"] == 0
    assert len(taken) == per_thread * thread_count
