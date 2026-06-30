"""Regression: a sample capture must preempt a running live H1 stream.

The H1 is single-owner: the coordinator serialises the live spectrum stream and
sample capture on one device lock, and the stream holds that lock for its whole
lifetime. Before the preempt fix, clicking "采集样本" while the live panel was
streaming made ``capture()`` block on the lock and time out with "capture busy".
``capture()`` (and every H1 control op) now SETS a preempt flag the stream checks
between frames, so the stream yields the device promptly and the capture succeeds.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from spectrum_acq.capture import create_mock_coordinator


def test_capture_preempts_active_stream(tmp_path: Path) -> None:
    coordinator = create_mock_coordinator(tmp_path / "data")

    first_frame = threading.Event()
    stream_error: list[BaseException] = []
    frames: list[dict] = []

    def run_stream() -> None:
        # max_frames=None -> the mock streams forever, holding the device lock the
        # whole time. Only a preempt (or close) ends it.
        try:
            for frame in coordinator.stream_h1():
                frames.append(frame)
                first_frame.set()
        except BaseException as exc:  # noqa: BLE001 - surface to the assertion
            stream_error.append(exc)

    streamer = threading.Thread(target=run_stream, name="test-h1-stream", daemon=True)
    streamer.start()

    # The stream owns the device lock once it has produced a frame.
    assert first_frame.wait(timeout=5.0), "stream never started"

    started = time.monotonic()
    result = coordinator.capture()
    elapsed = time.monotonic() - started

    assert result.sample_id, "capture did not produce a sample"
    # The handoff is a preempt, not a passive timeout: it must be well under the
    # device-acquire timeout (and nowhere near the old 5s "busy" cliff).
    assert elapsed < 5.0, f"capture waited {elapsed:.1f}s — looks like a busy timeout"

    # The stream broke out of its loop when preempted and released the lock.
    streamer.join(timeout=5.0)
    assert not streamer.is_alive(), "stream did not yield the device after preempt"
    assert not stream_error, f"stream raised: {stream_error!r}"
    assert frames, "stream produced no frames before being preempted"

    # The device is free again: a follow-up capture also succeeds.
    assert coordinator.capture().sample_id


def test_devices_reports_ready_in_use_while_lock_held(tmp_path: Path) -> None:
    """A live stream / capture holds the device lock for its lifetime. The status
    poll must NOT then report the actively-used H1 as not-ready (which the UI
    renders as "H1 未就绪" and uses to gate the stream off, causing it to flap).
    Once a good live read exists, a locked poll reports ready+in_use instead.
    """
    coordinator = create_mock_coordinator(tmp_path / "data")

    # Prime the last-known-good status (mock H1 reads READY).
    assert coordinator.devices()["h1"]["status"] == "ready"

    # Simulate a stream/capture owning the device lock during a status poll.
    assert coordinator._lock.acquire(blocking=False)
    try:
        h1 = coordinator.devices()["h1"]
    finally:
        coordinator._lock.release()

    assert h1["status"] == "ready", "locked poll must keep an in-use H1 'ready'"
    assert h1["in_use"] is True
    assert h1["stale"] is True
    assert h1["serial_number"]  # identity carried through from the cached read
