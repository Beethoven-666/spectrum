"""Background camera ownership: one owner thread per physical device.

The HTTP preview routes and the capture coordinator never touch a camera
directly. They read the latest cached frame from a :class:`CameraWorker`
(hardware) or a :class:`DirectStream` (mock). This decouples request rate from
USB I/O so that:

* the device is opened **once** and kept open (no per-frame open/close churn),
* frames are pulled on a controlled cadence into a thread-safe latest-frame
  cache,
* any device error tears the device down, backs off, and rebuilds it
  (self-healing) instead of wedging the pipeline forever, and
* a slow ``wait_for_frames`` never blocks an HTTP request thread.

The owner thread's whole decision logic lives in :meth:`CameraWorker._step`,
which uses an injectable ``clock``/``sleep`` so it can be unit-tested
synchronously with a fake adapter and zero real sleeping.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from spectrum_acq.models import DeviceStatus


class CameraTimeout(RuntimeError):
    """Raised when no fresh frame could be produced within the deadline."""


class StreamAdapter(Protocol):
    """Pure device I/O driven by a :class:`CameraWorker`.

    Every method is invoked **only** on the owner thread (except ``close``,
    which the worker may also call to unblock an in-flight ``read``); adapters
    therefore do not need their own locking beyond making ``close`` idempotent
    and safe to call from a second thread.
    """

    #: When True, ``read()`` blocks at the device's own frame rate, so the
    #: worker must not additionally sleep between reads (e.g. a RealSense
    #: pipeline configured at a low fps). When False the worker throttles to
    #: ``preview_fps`` itself (e.g. a UVC single-shot grab).
    paces_itself: bool

    def open(self) -> None: ...

    def read(self) -> Any: ...

    def close(self) -> None: ...

    def describe(self) -> dict[str, Any]: ...


@dataclass
class FrameHealth:
    """Liveness counters surfaced to the UI alongside the device status."""

    reconnecting: bool = False
    consecutive_failures: int = 0
    last_error: str | None = None
    frames_published: int = 0
    last_frame_monotonic: float | None = None

    def as_dict(self, *, now: float) -> dict[str, Any]:
        age = None if self.last_frame_monotonic is None else max(0.0, now - self.last_frame_monotonic)
        return {
            "reconnecting": self.reconnecting,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "frames_published": self.frames_published,
            "frame_age_s": age,
        }


def benign_health() -> dict[str, Any]:
    """Health payload for stand-ins that never fail (mock mode)."""

    return {
        "reconnecting": False,
        "consecutive_failures": 0,
        "last_error": None,
        "frames_published": 0,
        "frame_age_s": 0.0,
        "decode_failures": 0,
    }


class FrameBuffer:
    """Thread-safe holder for the latest frame with a monotonic sequence number.

    ``seq`` increments on every publish so waiters can detect a *new* frame
    (rather than re-reading a stale one). Fields are public but must only be
    read/written while holding :attr:`cond`.
    """

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.payload: Any | None = None
        self.monotonic: float = 0.0
        self.seq: int = 0

    def publish(self, payload: Any, *, monotonic: float) -> None:
        with self.cond:
            self.payload = payload
            self.monotonic = monotonic
            self.seq += 1
            self.cond.notify_all()

    def peek(self) -> tuple[Any | None, float, int]:
        with self.cond:
            return self.payload, self.monotonic, self.seq

    def clear(self) -> None:
        with self.cond:
            self.payload = None
            self.seq += 1
            self.cond.notify_all()


class CameraWorker:
    """Owns one device on a single thread; serves cached frames to everyone else."""

    def __init__(
        self,
        adapter: StreamAdapter,
        *,
        name: str,
        preview_fps: float,
        idle_timeout_s: float,
        backoff_min_s: float,
        backoff_max_s: float,
        max_frame_age_s: float,
        get_fresh_timeout_s: float,
        reopen_attempts_before_hw_reset: int = 5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._adapter = adapter
        self._name = name
        self._preview_fps = max(float(preview_fps), 0.1)
        self._idle_timeout_s = float(idle_timeout_s)
        self._backoff_min_s = float(backoff_min_s)
        self._backoff_max_s = float(backoff_max_s)
        self._max_frame_age_s = float(max_frame_age_s)
        self._get_fresh_timeout_s = float(get_fresh_timeout_s)
        self._reopen_before_hw_reset = int(reopen_attempts_before_hw_reset)
        self._clock = clock
        self._sleep = sleep
        self._idle_poll_s = min(0.25, max(self._idle_timeout_s, 0.01))

        self._buffer = FrameBuffer()
        self._health = FrameHealth()
        self._state_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._stop = threading.Event()
        self._paused = False
        self._last_demand = 0.0
        self._device_open = False
        self._reopen_failures = 0
        self._thread: threading.Thread | None = None
        self._describe: dict[str, Any] = self._safe_describe()

    # ------------------------------------------------------------------ API

    def note_demand(self) -> None:
        self._last_demand = self._clock()

    def preview(self) -> Any | None:
        """Latest cached frame (may be stale during a reconnect), or None."""
        self.note_demand()
        self._ensure_running()
        payload, _monotonic, _seq = self._buffer.peek()
        return payload

    def get_fresh(self, timeout: float | None = None) -> Any:
        """Block until a frame captured *after* this call, forcing the device open.

        Raises :class:`CameraTimeout` (carrying the latest health) if no fresh
        frame arrives within the deadline.
        """
        budget = self._get_fresh_timeout_s if timeout is None else float(timeout)
        deadline = self._clock() + budget
        self.resume()
        self.note_demand()
        self._ensure_running()
        with self._buffer.cond:
            target = self._buffer.seq
            while True:
                if self._buffer.payload is not None and self._buffer.seq > target:
                    return self._buffer.payload
                if self._stop.is_set():
                    break
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                self._buffer.cond.wait(timeout=min(remaining, 0.25))
        with self._state_lock:
            err = self._health.last_error
            reconnecting = self._health.reconnecting
        raise CameraTimeout(
            f"{self._name}: no fresh frame within {budget:.1f}s "
            f"(reconnecting={reconnecting}, last_error={err})"
        )

    def status(self) -> dict[str, Any]:
        now = self._clock()
        with self._state_lock:
            base = dict(self._describe)
            health = self._health.as_dict(now=now)
        health["decode_failures"] = int(getattr(self._adapter, "decode_failures", 0))
        base["status"] = self._derive_status(base, health)
        base["health"] = health
        return base

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def close(self) -> None:
        self._stop.set()
        # Unblock an in-flight read() (pipeline.stop / killing the subprocess).
        try:
            self._adapter.close()
        except Exception:
            pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._device_open = False
        with self._buffer.cond:
            self._buffer.cond.notify_all()

    # -------------------------------------------------------------- internals

    def _ensure_running(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        with self._start_lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name=f"cam-{self._name}", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self._step()
                except Exception as exc:  # noqa: BLE001 - never let the owner thread die
                    with self._state_lock:
                        self._health.last_error = f"loop: {exc}"
                    self._sleep(self._backoff_min_s)
        finally:
            try:
                self._adapter.close()
            except Exception:
                pass
            self._device_open = False

    def _step(self) -> None:
        """One iteration of the owner loop. Pure enough to unit-test directly."""
        if self._stop.is_set():
            return
        if self._paused or not self._demand_recent():
            self._ensure_closed()
            self._sleep(self._idle_poll_s)
            return
        if not self._device_open:
            self._open_or_backoff()
            return
        started = self._clock()
        try:
            payload = self._adapter.read()
        except Exception as exc:  # noqa: BLE001 - any read failure triggers self-heal
            self._handle_failure(exc)
            return
        self._on_frame(payload)
        if not getattr(self._adapter, "paces_itself", False):
            self._throttle_after(started)

    def _demand_recent(self) -> bool:
        return (self._clock() - self._last_demand) <= self._idle_timeout_s

    def _open_or_backoff(self) -> None:
        try:
            self._adapter.open()
        except Exception as exc:  # noqa: BLE001
            self._handle_failure(exc)
            return
        self._device_open = True
        with self._state_lock:
            self._health.reconnecting = False
            self._describe = self._safe_describe()

    def _on_frame(self, payload: Any) -> None:
        now = self._clock()
        self._buffer.publish(payload, monotonic=now)
        with self._state_lock:
            self._health.frames_published += 1
            self._health.last_frame_monotonic = now
            self._health.consecutive_failures = 0
            self._health.reconnecting = False
            self._health.last_error = None
        self._reopen_failures = 0

    def _handle_failure(self, exc: BaseException) -> None:
        self._ensure_closed()
        with self._state_lock:
            self._health.consecutive_failures += 1
            self._health.last_error = f"{type(exc).__name__}: {exc}"
            self._health.reconnecting = True
            failures = self._health.consecutive_failures
        self._reopen_failures += 1
        if self._reopen_failures >= self._reopen_before_hw_reset:
            self._maybe_hardware_reset()
            self._reopen_failures = 0
        self._sleep(self._backoff_duration(failures))

    def _backoff_duration(self, failures: int) -> float:
        return min(self._backoff_min_s * (2 ** max(failures - 1, 0)), self._backoff_max_s)

    def _maybe_hardware_reset(self) -> None:
        reset = getattr(self._adapter, "hardware_reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                pass

    def _ensure_closed(self) -> None:
        if not self._device_open:
            return
        try:
            self._adapter.close()
        except Exception:
            pass
        self._device_open = False
        # Keep the last frame in the buffer so preview() can show it (with a
        # "reconnecting" badge) instead of blanking during a brief hiccup.

    def _throttle_after(self, started: float) -> None:
        interval = 1.0 / self._preview_fps
        elapsed = self._clock() - started
        if elapsed < interval:
            self._sleep(interval - elapsed)

    def _safe_describe(self) -> dict[str, Any]:
        try:
            return dict(self._adapter.describe())
        except Exception as exc:  # noqa: BLE001
            return {"status": DeviceStatus.ERROR, "detail": {"error": str(exc)}}

    def _derive_status(self, base: dict[str, Any], health: dict[str, Any]) -> Any:
        age = health["frame_age_s"]
        if health["frames_published"] > 0 and age is not None and age <= self._max_frame_age_s:
            return DeviceStatus.READY
        if health["reconnecting"] or health["last_error"]:
            return DeviceStatus.ERROR
        return base.get("status", DeviceStatus.MISSING)


class DirectStream:
    """Synchronous, thread-free stand-in used in mock mode and tests.

    Exposes the same surface as :class:`CameraWorker` so the coordinator and
    routes are identical in mock and hardware mode, but every call runs inline
    on the caller's thread.
    """

    def __init__(
        self,
        *,
        read: Callable[[], Any],
        status: Callable[[], dict[str, Any]],
    ) -> None:
        self._read = read
        self._status = status

    def note_demand(self) -> None:
        return None

    def pause(self) -> None:
        return None

    def resume(self) -> None:
        return None

    def get_fresh(self, timeout: float | None = None) -> Any:
        return self._read()

    def preview(self) -> Any | None:
        return self._read()

    def status(self) -> dict[str, Any]:
        base = dict(self._status())
        base["health"] = benign_health()
        return base

    def close(self) -> None:
        return None
