"""Holds prediction records until there are enough to write as one batch.

Writing one object per request would leave MinIO full of tiny files and make
the monitoring DAG open thousands of them to read a single day. So records
accumulate here and leave in batches.

Three rules, in priority order:

1. Serving a request never waits on this and never fails because of it.
2. A failed flush keeps its records and retries; MinIO restarting for a few
   seconds must not lose monitoring data.
3. The buffer has a hard cap. Rule 2 without a cap means a long MinIO outage
   plus live traffic ends in an out-of-memory kill, so past the cap the oldest
   records are dropped and counted — loss stays bounded and visible at /health.

This module decides WHEN to flush and WHAT to drop. It never touches object
storage: the caller supplies the write. That keeps it testable with a list.

Every method takes a lock: serving adds from request threads while the flusher
takes from another, and take() is a copy followed by a clear — a record added
between the two would otherwise be cleared without ever being handed out.
"""

from __future__ import annotations

import threading
import time
from collections import deque

DEFAULT_FLUSH_SIZE = 500
DEFAULT_FLUSH_SECONDS = 30.0
DEFAULT_MAX_SIZE = 5000


class InferenceLogBuffer:
    """A bounded FIFO of prediction records with a size-or-age flush trigger.

    Example:
        buffer = InferenceLogBuffer(flush_size=500, flush_seconds=30)

        buffer.add({"request_id": "...", "prediction": 487312.5, ...})  # per request

        # The background flusher loop, once a second:
        if buffer.should_flush():
            records = buffer.take()
            try:
                write_batch(records)
            except Exception:
                buffer.give_back(records)   # MinIO blipped; retry next tick

        buffer.stats()  # -> {"buffered": 137, "dropped": 0}
    """

    def __init__(
        self,
        flush_size: int = DEFAULT_FLUSH_SIZE,
        flush_seconds: float = DEFAULT_FLUSH_SECONDS,
        max_size: int = DEFAULT_MAX_SIZE,
        clock=time.monotonic,
    ):
        """Sets the flush triggers and the hard cap.

        Args:
            flush_size: number of records that makes a batch ready to leave.
            flush_seconds: how long a non-empty buffer may wait before leaving
                anyway, so a trickle of traffic still gets written.
            max_size: hard cap. Past it the oldest records are dropped and
                counted — a long storage outage must not end in an OOM kill.
            clock: monotonic source of seconds, injectable so tests can move
                time without sleeping.

        Raises:
            ValueError: when flush_size exceeds max_size — the buffer would
                drop records before it ever reached a flush.
        """
        if flush_size > max_size:
            raise ValueError(
                f"flush_size ({flush_size}) cannot exceed max_size ({max_size}): "
                "the buffer would drop records before it ever flushed"
            )
        self._flush_size = flush_size
        self._flush_seconds = flush_seconds
        self._max_size = max_size
        self._clock = clock
        self._records: deque[dict] = deque()
        self._dropped = 0
        self._last_taken_at = clock()
        self._lock = threading.Lock()

    def _trim(self) -> None:
        """Drops the oldest records until the buffer is back within its cap.

        Args:
            None. Reads and mutates the buffer in place; the CALLER must
            already hold the lock.

        Returns:
            Nothing. Each dropped record is counted in `dropped`, which /health
            reports so the loss stays visible.

        Example:
            # max_size=5000, buffer holds 5002 after a give_back:
            self._trim()
            # -> the 2 OLDEST records are gone, self._dropped goes up by 2.
            # Oldest first, because the newest records are the ones that still
            # describe what production is doing right now.
        """
        while len(self._records) > self._max_size:
            self._records.popleft()
            self._dropped += 1

    def add(self, record: dict) -> None:
        """Appends one record, dropping the oldest if that puts us over the cap.

        Args:
            record: one prediction, as it will be written to object storage.

        Returns:
            Nothing, and never raises: serving a request must not fail because
            monitoring is having a bad day.

        Example:
            # The last thing /predict does before returning a response:
            buffer.add({
                "request_id": request_id,
                "timestamp": now.isoformat(),
                "day": now.date().isoformat(),   # decides which file it lands in
                "raw_input": json.dumps(record, default=str),
                "prediction": 487312.5,
                "model_name": "house_price_regressor",
                "model_version": "3",
            })
        """
        with self._lock:
            self._records.append(record)
            self._trim()

    def give_back(self, records: list[dict]) -> None:
        """Returns records a failed flush could not write, keeping their order.

        Args:
            records: exactly what a failed `take` handed out, still in order.

        Returns:
            Nothing. They go to the FRONT: they arrived before anything still
            buffered, and reordering them would scramble the timeline the
            monitoring DAG reads. If the buffer filled up while the write was
            failing, the cap still applies and the oldest are dropped.

        Example:
            records = buffer.take()       # -> [r1, r2, r3]
            # write fails
            buffer.give_back(records)
            buffer.take()                 # -> [r1, r2, r3, r4] if r4 arrived meanwhile
            # r1..r3 come back FIRST, not appended after r4.
        """
        with self._lock:
            self._records.extendleft(reversed(records))
            self._trim()

    def should_flush(self, now: float | None = None) -> bool:
        """Decides whether a batch is ready to leave.

        Args:
            now: the current time on the same scale as the clock, for tests
                that move time by hand. None reads the clock.

        Returns:
            True once the buffer holds flush_size records, or once flush_seconds
            have passed since the last `take`. An empty buffer returns False
            however old — otherwise serving would write an empty file every
            flush interval for as long as it idles.

        Example:
            # flush_size=500, flush_seconds=30
            buffer.should_flush()   # -> False, 12 records and 3 seconds old
            buffer.should_flush()   # -> True once the 500th record lands
            buffer.should_flush()   # -> True at 30s even with only 12 records
            # An empty buffer -> False, no matter how long it has idled.
        """
        with self._lock:
            if not self._records:
                return False
            if len(self._records) >= self._flush_size:
                return True
            current = self._clock() if now is None else now
            return (current - self._last_taken_at) >= self._flush_seconds

    def take(self) -> list[dict]:
        """Removes every buffered record and restarts the age timer.

        Args:
            None.

        Returns:
            The records in arrival order, or an empty list when there were
            none. The caller owns them from here: a write that fails must hand
            them back through `give_back` or they are lost.

        Example:
            records = buffer.take()
            # -> [r1, r2, r3]; the buffer is now empty and the 30s clock restarts.
            # From here the records exist ONLY in this list. Pair every take()
            # with a give_back() on the failure path.
        """
        with self._lock:
            taken = list(self._records)
            self._records.clear()
            self._last_taken_at = self._clock()
            return taken

    def stats(self) -> dict:
        """Reports the buffer's state for /health.

        Args:
            None.

        Returns:
            `buffered`, how many records are waiting right now, and `dropped`,
            how many were ever discarded at the cap. `dropped` is cumulative
            and never resets, so a past outage stays visible.

        Example:
            buffer.stats()  # -> {"buffered": 137, "dropped": 0}

            # This is the "inference_log" block of GET /health. A non-zero
            # `dropped` means monitoring data was lost to a storage outage —
            # predictions were still served correctly throughout.
        """
        with self._lock:
            return {"buffered": len(self._records), "dropped": self._dropped}
