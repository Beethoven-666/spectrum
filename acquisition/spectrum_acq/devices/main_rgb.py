"""V4L2 UVC adapter for the beamsplitter-aligned main RGB camera.

Two read strategies, selected by ``MainRgbProfile.mode``:

* ``persistent`` (default): hold one long-lived ``v4l2-ctl ... --stream-count=0
  --stream-to=-`` subprocess that streams MJPEG to stdout, and slice complete
  JPEG frames out of the byte stream. The device is opened **once** and kept
  open, eliminating the per-frame open/close churn that destabilises the shared
  Raspberry Pi USB bus.
* ``single_shot``: grab one frame per ``read`` via ``v4l2-ctl --stream-count=1``
  (the original behaviour). Still safe because the owning
  :class:`~spectrum_acq.devices.streaming.CameraWorker` drives it serially at a
  low cadence — but it does reopen the device each grab, so it is the
  conservative fallback if persistent streaming misbehaves on a given camera.

This module performs pure device I/O; threading, caching, throttling, and
self-healing live in the CameraWorker that owns the adapter.
"""

from __future__ import annotations

import io
import logging
import select
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from spectrum_acq.models import DeviceStatus, MainRgbProfile, utc_now_iso

from .interfaces import MainRgbCapture

logger = logging.getLogger(__name__)

_REALSENSE_MARKERS = ("RealSense", "Intel_R__RealSense")
_DEFAULT_BY_ID_GLOB = (
    "usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera-video-index0",
    "usb-*USB_2.0_Camera-video-index0",
)

_SOI = b"\xff\xd8"  # JPEG start-of-image marker
_EOI = b"\xff\xd9"  # JPEG end-of-image marker
_READ_CHUNK = 65536
_MAX_BUF = 4 * 1024 * 1024  # desync guard: never let the reassembly buffer grow unbounded


class MainRgbStreamStalled(RuntimeError):
    """Raised when the persistent stream produced no bytes within the deadline.

    A blocking ``proc.stdout.read`` cannot tell a slow-but-alive stream from a
    pipe that is open yet permanently silent (e.g. a Pi5 USB brownout that
    starves the camera). Surfacing this as an exception lets the owning
    CameraWorker tear the subprocess down and reopen it instead of wedging its
    owner thread forever.
    """


def _read_stream_chunk(stream: Any, *, timeout_s: float) -> bytes:
    """Read up to ``_READ_CHUNK`` bytes from ``stream`` within ``timeout_s``.

    Uses ``select.select`` to bound the wait when the stream exposes a real OS
    file descriptor (the live ``v4l2-ctl`` pipe). If the deadline passes with no
    data readable, raises :class:`MainRgbStreamStalled` so the worker self-heals.

    Streams without a usable ``fileno()`` (e.g. test fakes, in-memory buffers)
    fall back to a plain blocking ``read`` and are never subjected to ``select``;
    this keeps existing behaviour and unit tests intact.
    """
    fd: int | None = None
    fileno = getattr(stream, "fileno", None)
    if callable(fileno):
        try:
            fd = fileno()
        except (OSError, ValueError):
            fd = None  # not backed by a real fd (e.g. wrapped buffer): blocking read
    if fd is not None and fd >= 0:
        # select() returns the empty list on timeout; a stall therefore raises.
        readable, _, _ = select.select([fd], [], [], max(float(timeout_s), 0.0))
        if not readable:
            raise MainRgbStreamStalled(
                f"v4l2-ctl produced no bytes within {timeout_s:.1f}s (USB stall?)"
            )
    return stream.read(_READ_CHUNK)


def discover_main_rgb_device(
    *,
    by_id_dir: Path | str | None = None,
    exclude_markers: tuple[str, ...] = _REALSENSE_MARKERS,
) -> str | None:
    """Return a stable V4L2 by-id path for the main RGB camera, if present."""
    by_id = Path(by_id_dir) if by_id_dir is not None else Path("/dev/v4l/by-id")
    if not by_id.is_dir():
        return None

    def is_candidate(entry: Path) -> bool:
        name = entry.name
        if not name.endswith("-video-index0"):
            return False
        return not any(marker in name for marker in exclude_markers)

    preferred: list[Path] = []
    fallback: list[Path] = []
    for pattern in _DEFAULT_BY_ID_GLOB:
        for entry in sorted(by_id.glob(pattern)):
            if entry.is_symlink() and is_candidate(entry):
                preferred.append(entry)
    for entry in sorted(by_id.iterdir()):
        if entry.is_symlink() and is_candidate(entry) and entry not in preferred:
            fallback.append(entry)

    for entry in preferred + fallback:
        return str(entry)
    return None


def iter_complete_frames(buf: bytearray) -> Iterator[bytes]:
    """Yield and remove each complete JPEG (SOI..EOI) from ``buf``, in order.

    Junk before the first SOI is discarded. An incomplete trailing frame is left
    in the buffer for the next chunk. Pure and side-effecting on ``buf`` only —
    unit-tested directly.
    """
    while True:
        soi = buf.find(_SOI)
        if soi < 0:
            # No start marker yet; keep only a possible trailing 0xFF half-marker.
            if len(buf) > 1:
                del buf[:-1]
            return
        if soi > 0:
            del buf[:soi]
        eoi = buf.find(_EOI, len(_SOI))
        if eoi < 0:
            return  # frame not finished yet
        end = eoi + len(_EOI)
        frame = bytes(buf[:end])
        del buf[:end]
        yield frame


class V4l2MainRgbCamera:
    """Capture MJPEG frames from a UVC main RGB camera through ``v4l2-ctl``."""

    #: The worker throttles to preview_fps; read() does not pace itself.
    paces_itself = False

    def __init__(self, profile: MainRgbProfile) -> None:
        self.profile = profile
        self._mode = profile.mode
        self._resolved_device = profile.device_path or discover_main_rgb_device()
        self.decode_failures = 0
        self._proc: subprocess.Popen[bytes] | None = None
        self._buf = bytearray()

    # ------------------------------------------------------------ adapter API

    def open(self) -> None:
        if self._mode != "persistent":
            return  # single_shot grabs on each read()
        device = self._device_path()
        if device is None:
            raise RuntimeError("no UVC device found under /dev/v4l/by-id")
        if shutil.which("v4l2-ctl") is None:
            raise RuntimeError("v4l2-ctl not installed")
        self._close_persistent()
        fps = max(int(round(self.profile.preview_fps)), 1)
        cmd = [
            "v4l2-ctl",
            "-d",
            device,
            f"--set-fmt-video=width={self.profile.width},height={self.profile.height},"
            f"pixelformat={self.profile.pixel_format}",
            f"--set-parm={fps}",
            "--stream-mmap",
            "--stream-count=0",
            "--stream-to=-",
        ]
        self._buf = bytearray()
        self.decode_failures = 0
        self._proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def read(self) -> MainRgbCapture:
        if self._mode == "persistent":
            return self._read_persistent()
        return self._read_single_shot()

    def close(self) -> None:
        self._close_persistent()

    def describe(self) -> dict[str, Any]:
        return self.status()

    # ------------------------------------------------------------- persistent

    def _read_persistent(self) -> MainRgbCapture:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise RuntimeError("main RGB stream is not running")
        device = self._resolved_device
        while True:
            latest: bytes | None = None
            for frame in iter_complete_frames(self._buf):
                latest = frame  # keep only the freshest; older frames drained without decoding
            if latest is not None:
                try:
                    image = _decode_mjpeg(latest)
                except Exception:  # noqa: BLE001 - corrupt frame: count it and resync
                    self.decode_failures += 1
                    continue
                return MainRgbCapture(
                    status=DeviceStatus.READY,
                    captured_at=utc_now_iso(),
                    image_rgb=image,
                    metadata={
                        "driver": "v4l2",
                        "mode": "persistent",
                        "device_path": device,
                        "width": int(image.shape[1]),
                        "height": int(image.shape[0]),
                        "pixel_format": self.profile.pixel_format,
                    },
                )
            # Time-bounded read: a silent USB stall leaves the pipe open but
            # idle, so a bare blocking read would wedge this thread forever. On a
            # missed deadline _read_stream_chunk raises MainRgbStreamStalled,
            # which propagates to CameraWorker._step -> _handle_failure, tearing
            # down and reopening the subprocess (self-heal).
            chunk = _read_stream_chunk(proc.stdout, timeout_s=self.profile.timeout_s)
            if not chunk:
                raise RuntimeError("v4l2-ctl stream ended (stdout closed)")  # clean EOF
            self._buf += chunk
            if len(self._buf) > _MAX_BUF:
                last_soi = self._buf.rfind(_SOI)
                del self._buf[: last_soi if last_soi > 0 else len(self._buf)]

    def _close_persistent(self) -> None:
        proc = self._proc
        self._proc = None
        self._buf = bytearray()
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except Exception:
            pass

    # ------------------------------------------------------------ single shot

    def _read_single_shot(self) -> MainRgbCapture:
        device = self._device_path()
        if device is None:
            raise RuntimeError("no UVC device found under /dev/v4l/by-id")
        if shutil.which("v4l2-ctl") is None:
            raise RuntimeError("v4l2-ctl not installed")
        frame_bytes = _stream_mjpeg(
            device,
            width=self.profile.width,
            height=self.profile.height,
            pixel_format=self.profile.pixel_format,
            timeout_s=self.profile.timeout_s,
        )
        image = _decode_mjpeg(frame_bytes)
        return MainRgbCapture(
            status=DeviceStatus.READY,
            captured_at=utc_now_iso(),
            image_rgb=image,
            metadata={
                "driver": "v4l2",
                "mode": "single_shot",
                "device_path": device,
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
                "pixel_format": self.profile.pixel_format,
            },
        )

    # --------------------------------------------------------- status / helpers

    def status(self) -> dict[str, Any]:
        # Filesystem-only presence check: never touches the device, so it is safe
        # to call at startup, on every /devices poll, and while a persistent
        # stream holds the device open.
        device = self._device_path()
        if device is None:
            return {
                "status": DeviceStatus.MISSING,
                "name": "Main RGB camera",
                "serial": None,
                "detail": {
                    "driver": "v4l2",
                    "reason": "no UVC device found under /dev/v4l/by-id",
                },
            }
        if shutil.which("v4l2-ctl") is None:
            return {
                "status": DeviceStatus.ERROR,
                "name": "Main RGB camera",
                "serial": None,
                "detail": {"driver": "v4l2", "device_path": device, "error": "v4l2-ctl not installed"},
            }
        return {
            "status": DeviceStatus.READY,
            "name": "Main RGB camera",
            "serial": None,
            "detail": {
                "driver": "v4l2",
                "device_path": device,
                "mode": self._mode,
                "profile": {
                    "width": self.profile.width,
                    "height": self.profile.height,
                    "pixel_format": self.profile.pixel_format,
                },
            },
        }

    def capture(self) -> MainRgbCapture:
        """One-shot convenience grab (used by the Pi smoke script). Never raises."""
        captured_at = utc_now_iso()
        device = self._device_path()
        if device is None:
            return _missing_capture(captured_at, reason="no UVC device found")
        if shutil.which("v4l2-ctl") is None:
            return _error_capture(captured_at, device, "v4l2-ctl not installed")
        try:
            frame_bytes = _stream_mjpeg(
                device,
                width=self.profile.width,
                height=self.profile.height,
                pixel_format=self.profile.pixel_format,
                timeout_s=self.profile.timeout_s,
            )
            image_rgb = _decode_mjpeg(frame_bytes)
        except Exception as exc:  # noqa: BLE001 - surface hardware failures in metadata
            logger.warning("main RGB capture failed on %s: %s", device, exc)
            return _error_capture(captured_at, device, str(exc))
        return MainRgbCapture(
            status=DeviceStatus.READY,
            captured_at=captured_at,
            image_rgb=image_rgb,
            metadata={
                "driver": "v4l2",
                "mode": "single_shot",
                "device_path": device,
                "width": int(image_rgb.shape[1]),
                "height": int(image_rgb.shape[0]),
                "pixel_format": self.profile.pixel_format,
            },
        )

    def _device_path(self) -> str | None:
        configured = self.profile.device_path
        if configured:
            path = Path(configured)
            if path.exists():
                return str(path)
            return None
        self._resolved_device = discover_main_rgb_device()
        return self._resolved_device


def _missing_capture(captured_at: str, *, reason: str) -> MainRgbCapture:
    return MainRgbCapture(
        status=DeviceStatus.MISSING,
        captured_at=captured_at,
        image_rgb=None,
        metadata={"driver": "v4l2", "reason": reason},
    )


def _error_capture(captured_at: str, device: str, error: str) -> MainRgbCapture:
    return MainRgbCapture(
        status=DeviceStatus.ERROR,
        captured_at=captured_at,
        image_rgb=None,
        metadata={"driver": "v4l2", "device_path": device, "error": error},
    )


def _stream_mjpeg(
    device: str,
    *,
    width: int,
    height: int,
    pixel_format: str,
    timeout_s: float,
) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        cmd = [
            "v4l2-ctl",
            "-d",
            device,
            f"--set-fmt-video=width={width},height={height},pixelformat={pixel_format}",
            "--stream-mmap",
            "--stream-count=1",
            f"--stream-to={tmp_path}",
        ]
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(detail or f"v4l2-ctl exited with code {result.returncode}")
        data = tmp_path.read_bytes()
        if len(data) < 256:
            raise RuntimeError(f"main RGB frame too small: {len(data)} bytes")
        return data
    finally:
        tmp_path.unlink(missing_ok=True)


def _decode_mjpeg(data: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    return np.asarray(image, dtype=np.uint8)


def create_main_rgb_provider(*, mock: bool, profile: MainRgbProfile) -> Any:
    """Return the raw main-RGB device adapter (mock or hardware).

    The capture coordinator wraps this in a CameraWorker (hardware) or
    DirectStream (mock); callers that want frames should go through that wrapper.
    """
    from .mock import NullMainRgbProvider

    if mock:
        return NullMainRgbProvider()
    return V4l2MainRgbCamera(profile)
