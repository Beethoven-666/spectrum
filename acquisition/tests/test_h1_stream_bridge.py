"""Regression tests for the H1 SSE stream bridge.

The device SDK holds a ``threading.RLock`` across the whole stream and releases it
in the generator's ``finally``. An RLock may only be released by the thread that
acquired it, so the bridge must iterate AND close the sync generator on a single
thread. These tests fail (lock wedged) if that invariant is broken.
"""

from __future__ import annotations

import asyncio
import threading

from spectrum_acq.api.h1_routes import _bridge_sync_stream


def _drain(make_gen) -> list[str]:
    async def collect() -> list[str]:
        out: list[str] = []
        async for event in _bridge_sync_stream(make_gen):
            out.append(event)
        return out

    return asyncio.run(collect())


def test_bridge_releases_rlock_on_acquiring_thread() -> None:
    rlock = threading.RLock()  # same primitive the H1 Device uses
    state = {"closed": False}

    def make_gen():
        rlock.acquire()  # like Device._stream_iterator
        try:
            for i in range(3):
                yield {"i": i}
        finally:
            rlock.release()  # RLock: raises if released off the acquiring thread
            state["closed"] = True

    events = _drain(make_gen)

    assert state["closed"] is True
    # If teardown ran on the wrong thread, release() would have raised and the
    # lock would still be held — this acquire would fail.
    assert rlock.acquire(blocking=False) is True
    rlock.release()
    assert sum("event: frame" in e for e in events) == 3
    assert not any("event: error" in e for e in events)


def test_bridge_emits_error_event_without_wedging() -> None:
    rlock = threading.RLock()

    def make_gen():
        rlock.acquire()
        try:
            yield {"i": 0}
            raise RuntimeError("boom")
        finally:
            rlock.release()

    events = _drain(make_gen)

    assert any("event: error" in e and "boom" in e for e in events)
    assert rlock.acquire(blocking=False) is True  # not wedged
    rlock.release()


def test_bridge_closes_generator_on_consumer_abort() -> None:
    rlock = threading.RLock()
    done = threading.Event()

    def make_gen():
        rlock.acquire()
        try:
            i = 0
            while True:
                yield {"i": i}
                i += 1
        finally:
            rlock.release()
            done.set()

    async def consume_one() -> None:
        agen = _bridge_sync_stream(make_gen)
        async for event in agen:
            if "event: frame" in event:
                break  # simulate client disconnect after the first frame
        await agen.aclose()  # triggers stop -> worker closes the gen on its thread

    asyncio.run(consume_one())

    # Worker closes the generator on its own thread shortly after the stop signal.
    assert done.wait(timeout=5.0) is True
    assert rlock.acquire(blocking=False) is True  # lock freed, device not wedged
    rlock.release()
