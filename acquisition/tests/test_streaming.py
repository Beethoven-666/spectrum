"""Tests for the camera owner-thread worker.

The bulk of the logic is exercised synchronously by driving ``_step()`` with an
injected clock + recording sleep (no real threads, no real sleeping). A handful
of bounded real-thread tests cover ``get_fresh``/``preview``/``close``.
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from spectrum_acq.devices.streaming import (
    CameraTimeout,
    CameraWorker,
    DirectStream,
    benign_health,
)
from spectrum_acq.models import DeviceStatus


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class RecordingSleep:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.calls: list[float] = []
        self._clock = clock

    def __call__(self, dt: float) -> None:
        self.calls.append(dt)
        if self._clock is not None:
            self._clock.advance(dt)


class FakeAdapter:
    """Synchronous, fully scripted adapter for ``_step`` tests."""

    paces_itself = False

    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0
        self.reads = 0
        self.open_error: BaseException | None = None
        self.read_error: BaseException | None = None
        self.decode_failures = 0

    def open(self) -> None:
        self.opened += 1
        if self.open_error is not None:
            raise self.open_error

    def read(self) -> dict:
        self.reads += 1
        if self.read_error is not None:
            err, self.read_error = self.read_error, None
            raise err
        return {"frame": self.reads}

    def close(self) -> None:
        self.closed += 1

    def describe(self) -> dict:
        return {"status": DeviceStatus.READY, "name": "fake"}


class BlockingAdapter:
    """Adapter whose ``read`` blocks until the test feeds a payload."""

    paces_itself = True  # so the worker never throttle-sleeps

    _SENTINEL = object()

    def __init__(self) -> None:
        self.q: queue.Queue = queue.Queue()
        self.opened = 0
        self.closed = 0

    def open(self) -> None:
        self.opened += 1

    def read(self) -> dict:
        item = self.q.get()
        if item is self._SENTINEL:
            raise RuntimeError("closed")
        return item

    def close(self) -> None:
        self.closed += 1
        self.q.put(self._SENTINEL)  # unblock an in-flight read()

    def describe(self) -> dict:
        return {"status": DeviceStatus.READY, "name": "blocking"}


def make_worker(adapter, *, clock=None, sleep=None, **overrides) -> CameraWorker:
    kwargs = dict(
        name="test",
        preview_fps=10.0,
        idle_timeout_s=15.0,
        backoff_min_s=0.5,
        backoff_max_s=30.0,
        max_frame_age_s=2.0,
        get_fresh_timeout_s=8.0,
    )
    kwargs.update(overrides)
    if clock is not None:
        kwargs["clock"] = clock
    if sleep is not None:
        kwargs["sleep"] = sleep
    return CameraWorker(adapter, **kwargs)


# --------------------------------------------------------------- _step logic


def test_step_opens_then_publishes_on_demand() -> None:
    clock = FakeClock()
    sleep = RecordingSleep(clock)
    adapter = FakeAdapter()
    worker = make_worker(adapter, clock=clock, sleep=sleep)

    worker.note_demand()
    worker._step()  # closed + demand -> open
    assert adapter.opened == 1
    worker._step()  # open -> read + publish + throttle
    payload, _ts, seq = worker._buffer.peek()
    assert payload == {"frame": 1}
    assert seq == 1
    # throttled to preview_fps (1/10s) since the fake read was instant
    assert sleep.calls[-1] == pytest.approx(0.1)


def test_step_idle_closes_after_timeout() -> None:
    clock = FakeClock()
    sleep = RecordingSleep()
    adapter = FakeAdapter()
    worker = make_worker(adapter, clock=clock, sleep=sleep)

    worker.note_demand()
    worker._step()  # open
    worker._step()  # read
    assert adapter.closed == 0

    clock.advance(16.0)  # past idle_timeout with no new demand
    worker._step()
    assert adapter.closed == 1
    assert worker._device_open is False


def test_step_self_heals_on_read_failure() -> None:
    clock = FakeClock()
    sleep = RecordingSleep()
    adapter = FakeAdapter()
    worker = make_worker(adapter, clock=clock, sleep=sleep)

    worker.note_demand()
    worker._step()  # open
    adapter.read_error = RuntimeError("boom")
    worker._step()  # read raises -> close + backoff
    assert adapter.closed == 1
    assert worker._health.consecutive_failures == 1
    assert worker._health.reconnecting is True
    assert "boom" in (worker._health.last_error or "")
    assert sleep.calls[-1] == pytest.approx(0.5)  # backoff_min

    worker._step()  # reopen
    assert adapter.opened == 2
    worker._step()  # read succeeds -> recovery
    assert worker._health.reconnecting is False
    assert worker._health.consecutive_failures == 0


def test_backoff_is_exponential_and_capped() -> None:
    clock = FakeClock()
    sleep = RecordingSleep()  # does not advance clock -> demand stays recent
    adapter = FakeAdapter()
    adapter.open_error = RuntimeError("no device")
    worker = make_worker(adapter, clock=clock, sleep=sleep, backoff_max_s=2.5)

    worker.note_demand()
    for _ in range(4):
        worker._step()  # each: open fails -> backoff
    assert sleep.calls == [0.5, 1.0, 2.0, 2.5]  # 0.5, 1, 2, capped at 2.5


def test_demand_kept_warm_does_not_close() -> None:
    clock = FakeClock()
    sleep = RecordingSleep()
    adapter = FakeAdapter()
    worker = make_worker(adapter, clock=clock, sleep=sleep)

    worker.note_demand()
    worker._step()  # open
    for _ in range(5):
        clock.advance(5.0)
        worker.note_demand()  # refresh within idle window
        worker._step()
    assert adapter.closed == 0
    assert worker._device_open is True


# ------------------------------------------------------------ status / shape


def test_status_merges_device_and_health() -> None:
    worker = make_worker(FakeAdapter(), clock=FakeClock())
    status = worker.status()
    assert status["status"] == DeviceStatus.READY  # from describe(), no frames yet
    assert status["name"] == "fake"
    health = status["health"]
    assert set(health) == {
        "reconnecting",
        "consecutive_failures",
        "last_error",
        "frames_published",
        "frame_age_s",
        "decode_failures",
    }
    assert health["reconnecting"] is False


def test_status_shape_parity_between_worker_and_directstream() -> None:
    worker = make_worker(FakeAdapter(), clock=FakeClock())
    direct = DirectStream(
        read=lambda: {"x": 1},
        status=lambda: {"status": DeviceStatus.READY, "name": "mock"},
    )
    ws, ds = worker.status(), direct.status()
    assert "status" in ws and "status" in ds
    assert set(ws["health"]) == set(ds["health"])


def test_reconnecting_surfaces_as_error_status() -> None:
    clock = FakeClock()
    adapter = FakeAdapter()
    adapter.open_error = RuntimeError("usb gone")
    worker = make_worker(adapter, clock=clock, sleep=RecordingSleep())
    worker.note_demand()
    worker._step()  # open fails -> reconnecting
    assert worker.status()["status"] == DeviceStatus.ERROR


# --------------------------------------------------------------- DirectStream


def test_directstream_is_synchronous_passthrough() -> None:
    before = threading.active_count()
    ds = DirectStream(
        read=lambda: {"frame": 7},
        status=lambda: {"status": DeviceStatus.MISSING, "name": "null"},
    )
    assert ds.get_fresh() == {"frame": 7}
    assert ds.preview() == {"frame": 7}
    status = ds.status()
    assert status["status"] == DeviceStatus.MISSING
    assert status["health"] == benign_health()
    ds.close()
    ds.note_demand()
    assert threading.active_count() == before  # no threads spawned


# ---------------------------------------------------------- threaded get_fresh


def test_get_fresh_returns_a_frame_after_the_call() -> None:
    adapter = BlockingAdapter()
    worker = make_worker(adapter, idle_timeout_s=100.0, get_fresh_timeout_s=5.0)
    result: dict = {}

    def grab() -> None:
        result["value"] = worker.get_fresh()

    thread = threading.Thread(target=grab)
    thread.start()
    try:
        time.sleep(0.05)  # let the worker open + block in read()
        adapter.q.put({"frame": "fresh"})
        thread.join(timeout=3.0)
        assert not thread.is_alive()
        assert result["value"] == {"frame": "fresh"}
    finally:
        worker.close()
    assert adapter.closed >= 1


def test_get_fresh_times_out_with_health() -> None:
    adapter = BlockingAdapter()  # never produces a frame
    worker = make_worker(adapter, idle_timeout_s=100.0)
    try:
        with pytest.raises(CameraTimeout) as excinfo:
            worker.get_fresh(timeout=0.3)
        assert "test" in str(excinfo.value)
    finally:
        worker.close()


def test_preview_warms_up_then_serves_cached() -> None:
    adapter = BlockingAdapter()
    worker = make_worker(adapter, idle_timeout_s=100.0)
    try:
        assert worker.preview() is None  # no frame yet (read is blocking)
        adapter.q.put({"frame": 1})
        deadline = time.monotonic() + 2.0
        while worker.preview() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert worker.preview() == {"frame": 1}
    finally:
        worker.close()


def test_close_joins_thread_and_releases_device() -> None:
    adapter = BlockingAdapter()
    worker = make_worker(adapter, idle_timeout_s=100.0)
    worker.preview()  # starts the owner thread
    time.sleep(0.05)
    worker.close()
    assert worker._thread is None or not worker._thread.is_alive()
    assert adapter.closed >= 1
