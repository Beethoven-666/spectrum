"""Capture coordinator for H1 + D455 + optional main RGB."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from spectrum_acq.config import default_config
from spectrum_acq.devices.h1 import H1DeviceAdapter
from spectrum_acq.devices.interfaces import (
    CameraStream,
    D455Snapshot,
    H1Spectrometer,
    MainRgbCapture,
)
from spectrum_acq.devices.main_rgb import V4l2MainRgbCamera
from spectrum_acq.devices.mock import MockD455Camera, MockH1Spectrometer, NullMainRgbProvider
from spectrum_acq.devices.streaming import CameraTimeout, CameraWorker, DirectStream
from spectrum_acq.geometry import compute_geometry
from spectrum_acq.geometry.pointcloud import GeometryResult, PointCloudResult
from spectrum_acq.models import (
    AcquisitionConfig,
    CaptureResult,
    CaptureState,
    DeviceStatus,
    QualityStatus,
    Roi,
    SCHEMA_VERSION,
    to_jsonable,
    utc_now_iso,
)
from spectrum_acq.storage import SampleStore


# How long a device-acquiring call (a sample capture or an H1 control op) waits to
# take the single device lock from a running live stream. The live H1 stream holds
# the lock for its whole lifetime and only yields the device when it tears the SDK
# generator down: it stops yielding (observed between frames), sends CMD 0x04 and
# drains trailing frames (up to roughly one exposure-cap period, PROTOCOL.md §8.2)
# before releasing the lock. That teardown routinely takes several seconds, so a
# short acquire timeout surfaces a spurious "capture busy" even though the stream
# is in the act of yielding the device. We preempt the stream (see ``_preempt``)
# and wait comfortably longer than the worst-case teardown window.
_DEVICE_ACQUIRE_TIMEOUT_S = 15.0

# A newly opened live stream waits this long for an in-flight capture/control op to
# finish before reporting busy. A sample capture runs auto-exposure convergence
# (seconds), so the stream needs room before it gives up.
_STREAM_ACQUIRE_TIMEOUT_S = 12.0


class CaptureCoordinator:
    def __init__(
        self,
        *,
        config: AcquisitionConfig,
        h1: H1Spectrometer,
        d455: CameraStream,
        main_rgb: CameraStream,
        store: SampleStore | None = None,
    ) -> None:
        self.config = config
        self.h1 = h1
        self.d455 = d455
        self.main_rgb = main_rgb
        self.store = store or SampleStore(config)
        self._lock = threading.Lock()
        # Set by a capture/control op that wants the device while a live stream
        # holds the lock. The stream loop checks it between frames and breaks so
        # the lock is handed over promptly instead of the caller timing out.
        self._preempt = threading.Event()
        self._state = CaptureState.IDLE
        self._current: dict[str, Any] = {"state": self._state, "sample_id": None, "error": None}
        self._last_h1_status: dict[str, Any] | None = None

    @property
    def state(self) -> dict[str, Any]:
        return to_jsonable(self._current)

    def devices(self) -> dict[str, Any]:
        if self._lock.acquire(blocking=False):
            try:
                h1_status = to_jsonable(self.h1.status())
                self._last_h1_status = h1_status
            finally:
                self._lock.release()
        else:
            # The H1 is single-owner: while a capture/stream holds the lock we
            # cannot read a live status. The lock is almost always held because
            # OUR OWN live spectrum stream (or a capture) is using the device — in
            # which case the device demonstrably opened and is working, so we must
            # NOT report it as not-ready. Previously this returned status="busy",
            # which the UI renders as "H1 未就绪" (red) and, worse, uses to gate the
            # live stream off — so an actively-streaming H1 flapped between ready
            # and "未就绪" every status poll. When the last live read was READY we
            # therefore report that cached status, flagged ``stale``/``in_use`` so
            # the UI keeps showing the device online without claiming a fresh read.
            # Only when we never got a good read (or it was an error) do we fall
            # back to an explicit "busy" so a genuine failure isn't masked.
            last = self._last_h1_status or {}
            if last.get("status") == "ready":
                h1_status = {**last, "stale": True, "in_use": True}
            else:
                h1_status = {
                    "status": "busy",
                    "stale": True,
                    "serial_number": last.get("serial_number"),
                    "wavelength_range": last.get("wavelength_range"),
                    "exposure_time_us": last.get("exposure_time_us"),
                    "exposure_mode": last.get("exposure_mode"),
                    "max_exposure_time_us": last.get("max_exposure_time_us"),
                    "detail": {
                        "reason": "busy",
                        "error": "H1 capture or stream is busy; status is stale",
                    },
                }
        return {
            "h1": h1_status,
            "d455": to_jsonable(self.d455.status()),
            "main_rgb": to_jsonable(self.main_rgb.status()),
        }

    def _acquire_device(self, timeout: float, *, preempt: bool) -> bool:
        """Take the single device lock, optionally preempting a running stream.

        The live H1 stream holds the lock for its whole lifetime and only checks
        for a preemption request between frames. A capture or control op therefore
        SETS ``_preempt`` before blocking on the lock, so the stream breaks out of
        its loop, tears the SDK generator down (CMD 0x04 + drain + RLock release on
        its own thread) and releases the lock — instead of the caller passively
        timing out with "capture busy". Whoever wins the lock clears the flag so its
        own work (including a freshly started stream) is not self-preempted; that
        clear also self-heals a flag left set by an acquire that timed out.
        """
        if preempt:
            self._preempt.set()
        acquired = self._lock.acquire(timeout=timeout)
        if acquired:
            self._preempt.clear()
        return acquired

    def stream_h1(
        self,
        *,
        include_tm30: bool = False,
        max_frames: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        if not self._acquire_device(_STREAM_ACQUIRE_TIMEOUT_S, preempt=False):
            raise RuntimeError("capture busy")
        # Hold an explicit reference so we can close the inner generator ON THIS
        # THREAD in the finally — that runs the SDK stop/drain and releases the
        # device RLock on the acquiring thread (closing it off-thread would hit the
        # RLock cross-thread release bug). A plain ``for`` (vs ``yield from``) lets
        # us interleave the preempt check between frames.
        inner = self.h1.stream(
            include_tm30=include_tm30,
            max_frames=max_frames,
            config=self.config.h1_auto_exposure,
        )
        try:
            for frame in inner:
                yield frame
                # A capture or control op is waiting for the device — yield it now.
                if self._preempt.is_set():
                    break
        finally:
            # Release the lock even if the SDK teardown raises — a wedged lock is
            # exactly the failure we are fixing.
            try:
                inner.close()
            finally:
                self._lock.release()

    def _run_h1_locked(self, fn, *, timeout: float = _DEVICE_ACQUIRE_TIMEOUT_S):
        if not self._acquire_device(timeout, preempt=True):
            raise RuntimeError("capture busy")
        try:
            return fn()
        finally:
            self._lock.release()

    def h1_device_info(self) -> dict[str, Any]:
        return self._run_h1_locked(self.h1.device_info)

    def h1_get_exposure(self) -> dict[str, Any]:
        return self._run_h1_locked(self.h1.get_exposure)

    def h1_patch_exposure(
        self,
        *,
        mode: str | None = None,
        time_us: int | None = None,
        max_time_us: int | None = None,
    ) -> dict[str, Any]:
        return self._run_h1_locked(
            lambda: self.h1.patch_exposure(mode=mode, time_us=time_us, max_time_us=max_time_us)
        )

    def h1_get_cie_mode(self) -> dict[str, str]:
        return self._run_h1_locked(self.h1.get_cie_mode)

    def h1_set_cie_mode(self, mode_name: str) -> dict[str, str]:
        return self._run_h1_locked(lambda: self.h1.set_cie_mode(mode_name))

    def h1_set_working_mode(self, mode: str) -> dict[str, str]:
        return self._run_h1_locked(lambda: self.h1.set_working_mode(mode))

    def h1_enter_sleep(self) -> dict[str, Any]:
        return self._run_h1_locked(self.h1.enter_sleep)

    def h1_exit_sleep(self) -> dict[str, Any]:
        return self._run_h1_locked(self.h1.exit_sleep)

    def h1_capture_single(self, *, include_tm30: bool = False) -> dict[str, Any]:
        return self._run_h1_locked(lambda: self.h1.capture_single_frame(include_tm30=include_tm30))

    def h1_upload_efficiency_curve(self, ratios: list[float]) -> dict[str, Any]:
        return self._run_h1_locked(lambda: self.h1.upload_efficiency_curve(ratios))

    def h1_verify_efficiency_curve(self) -> dict[str, Any]:
        return self._run_h1_locked(self.h1.verify_efficiency_curve)

    def h1_reset_efficiency_curve(self) -> dict[str, Any]:
        return self._run_h1_locked(self.h1.reset_efficiency_curve)

    def capture(
        self,
        *,
        roi: Roi | None = None,
        exposure_mode: str | None = None,
        force: bool = False,
    ) -> CaptureResult:
        if not self._acquire_device(_DEVICE_ACQUIRE_TIMEOUT_S, preempt=True):
            raise RuntimeError("capture busy")
        sample_id = make_sample_id()
        started_wall = utc_now_iso()
        started_mono = time.monotonic()
        try:
            self._set_state(CaptureState.CAPTURE_REQUESTED, sample_id=sample_id)
            storage_status = self.store.storage_status()
            if (
                storage_status["free_bytes"] <= self.config.disk.stop_free_bytes
                and not (force or self.config.disk.allow_below_stop)
            ):
                raise RuntimeError("low disk space")

            active_roi = (roi or self.config.roi).clamp()
            h1_config = self.config.h1_auto_exposure
            if exposure_mode is not None:
                h1_config = type(h1_config)(**{**asdict(h1_config), "mode": exposure_mode})

            self._set_state(CaptureState.CAPTURING, sample_id=sample_id)
            # M10: the D455 can brown out (Pi5 USB under-voltage) and time out
            # mid-capture. The spectrum is the irreplaceable measurement, so when
            # the operator has opted in via ``force`` we degrade to a
            # spectrum-only sample (geometry omitted, quality BAD) rather than
            # discarding a good H1 reading. Without ``force`` the timeout still
            # fails the capture, matching the strict-exposure gate above.
            depth_available = True
            try:
                d455_snapshot = self.d455.get_fresh()
            except CameraTimeout as exc:
                if not force:
                    raise
                depth_available = False
                d455_snapshot = _depth_unavailable_snapshot(str(exc))
            h1_capture = self.h1.capture_auto(h1_config)
            if (
                h1_config.mode == "strict"
                and h1_capture.selected_attempt.exposure_status != "normal"
                and not force
            ):
                raise RuntimeError(
                    f"H1 strict exposure failed: {h1_capture.selected_attempt.exposure_status}"
                )
            main_rgb_capture = self._capture_main_rgb()

            if depth_available:
                pointcloud, geometry = compute_geometry(
                    d455_snapshot.depth_mm,
                    d455_snapshot.intrinsics,
                    active_roi,
                    self.config.quality,
                )
            else:
                # No depth frame: emit an empty point cloud and an "unavailable"
                # geometry result carrying a depth_unavailable warning so the
                # sample is clearly marked BAD downstream (see _quality).
                pointcloud, geometry = _depth_unavailable_geometry()
            quality = self._quality(
                h1_capture=h1_capture,
                d455_snapshot=d455_snapshot,
                main_rgb_status=str(main_rgb_capture.status),
                geometry=geometry,
                storage_status=storage_status,
            )
            ended_mono = time.monotonic()
            metadata = self._metadata(
                sample_id=sample_id,
                started_wall=started_wall,
                ended_wall=utc_now_iso(),
                started_mono=started_mono,
                ended_mono=ended_mono,
                roi=active_roi,
                h1_capture=h1_capture,
                d455_snapshot=d455_snapshot,
                main_rgb_capture=main_rgb_capture,
                storage_status=storage_status,
            )
            self._set_state(CaptureState.WRITING, sample_id=sample_id)
            result = self.store.write_sample(
                sample_id=sample_id,
                h1=h1_capture,
                d455=d455_snapshot,
                main_rgb=main_rgb_capture,
                pointcloud=pointcloud,
                geometry=geometry,
                roi=active_roi,
                quality=quality,
                metadata=metadata,
            )
            self._set_state(CaptureState.DONE, sample_id=sample_id, result=to_jsonable(result))
            return result
        except Exception as exc:
            self._set_state(CaptureState.FAILED, sample_id=sample_id, error=str(exc))
            raise
        finally:
            self._lock.release()

    def _quality(
        self,
        *,
        h1_capture,
        d455_snapshot,
        main_rgb_status: str,
        geometry,
        storage_status: dict[str, Any],
    ) -> dict[str, Any]:
        warnings: list[str] = []
        status = QualityStatus.GOOD
        exposure_status = h1_capture.selected_attempt.exposure_status
        if exposure_status != "normal":
            warnings.append(f"h1_exposure_{exposure_status}")
            status = QualityStatus.WARN
        warnings.extend(geometry.warnings)
        if geometry.warnings:
            status = QualityStatus.WARN
        # M10: a missing depth frame (degraded, force-only capture) is as
        # disqualifying for geometry as a bad angle/unknown distance — mark BAD.
        if any(w in geometry.warnings for w in ["angle_bad", "distance_unknown", "depth_unavailable"]):
            status = QualityStatus.BAD
        if storage_status["status"] == QualityStatus.WARN:
            warnings.append("disk_space_warn")
            status = max_quality(status, QualityStatus.WARN)
        if storage_status["status"] == QualityStatus.BAD:
            warnings.append("disk_space_bad")
            status = QualityStatus.BAD
        if main_rgb_status in {str(DeviceStatus.MISSING), str(DeviceStatus.DISABLED)}:
            warnings.append("main_rgb_missing")
            status = max_quality(status, QualityStatus.WARN)
        imu = d455_snapshot.imu
        if imu.get("available") and (
            abs(float(imu.get("delta_roll_deg", 0.0))) > self.config.quality.max_imu_delta_deg
            or abs(float(imu.get("delta_pitch_deg", 0.0))) > self.config.quality.max_imu_delta_deg
        ):
            warnings.append("imu_motion_warn")
            status = max_quality(status, QualityStatus.WARN)

        return {
            "status": status,
            "warnings": sorted(set(warnings)),
            "h1": {
                "exposure_status": exposure_status,
                "selected_attempt": to_jsonable(h1_capture.selected_attempt),
            },
            "geometry": {
                "distance_mm": geometry.distance_mm,
                "depth_valid_ratio": geometry.depth_valid_ratio,
                "normal_camera": geometry.normal_camera,
                "angle_deg": geometry.angle_deg,
                "status": geometry.status,
                "detail": geometry.detail,
            },
            "d455": {
                "imu": d455_snapshot.imu,
                "captured_at": d455_snapshot.captured_at,
            },
            "storage": storage_status,
        }

    def _metadata(
        self,
        *,
        sample_id: str,
        started_wall: str,
        ended_wall: str,
        started_mono: float,
        ended_mono: float,
        roi: Roi,
        h1_capture,
        d455_snapshot,
        main_rgb_capture,
        storage_status: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "sample_id": sample_id,
            "created_at": started_wall,
            "ended_at": ended_wall,
            "timing": {
                "monotonic_start_s": started_mono,
                "monotonic_end_s": ended_mono,
                "duration_ms": (ended_mono - started_mono) * 1000.0,
                "software_sync": {
                    "h1_selected_attempt": to_jsonable(h1_capture.selected_attempt),
                    "d455_captured_at": d455_snapshot.captured_at,
                    "main_rgb_captured_at": main_rgb_capture.captured_at,
                },
            },
            "software": {
                "service": "spectrum-acq",
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "devices": {
                "h1": {
                    "status": str(h1_capture.status.status),
                    "serial_number": h1_capture.status.serial_number,
                    "wavelength_range": h1_capture.status.wavelength_range,
                    "exposure_time_us": h1_capture.selected_attempt.exposure_time_us,
                    "exposure_mode": h1_capture.status.exposure_mode,
                    "max_exposure_time_us": h1_capture.status.max_exposure_time_us,
                },
                "d455": {
                    "status": str(d455_snapshot.status),
                    "serial": d455_snapshot.profile.get("serial"),
                    "profile": d455_snapshot.profile,
                    "intrinsics": d455_snapshot.intrinsics,
                },
                "main_rgb": {
                    "status": str(main_rgb_capture.status),
                    "metadata": main_rgb_capture.metadata,
                },
            },
            "roi": to_jsonable(roi),
            "calibration": {
                "status": "uncalibrated" if self.config.calibration_path is None else "configured",
                "version": None if self.config.calibration_path is None else Path(self.config.calibration_path).stem,
                "path": None if self.config.calibration_path is None else str(self.config.calibration_path),
            },
            "config": {
                "profile": "mock" if self.config.mock else "default",
                "d455_profile": to_jsonable(self.config.d455_profile),
                "h1_auto_exposure": to_jsonable(self.config.h1_auto_exposure),
                "quality": to_jsonable(self.config.quality),
            },
            "storage": storage_status,
        }

    def _capture_main_rgb(self) -> MainRgbCapture:
        """Grab a fresh main RGB frame, treating absence/failure as non-fatal.

        The main RGB camera is optional; a missing or wedged camera must warn the
        sample (via quality) rather than fail the whole capture.
        """
        try:
            return self.main_rgb.get_fresh()
        except Exception as exc:  # noqa: BLE001 - optional device, degrade gracefully
            return MainRgbCapture(
                status=DeviceStatus.MISSING,
                captured_at=utc_now_iso(),
                image_rgb=None,
                metadata={"driver": "v4l2", "reason": str(exc)},
            )

    def _set_state(self, state: CaptureState, **kwargs: Any) -> None:
        self._state = state
        self._current = {"state": state, **kwargs}

    def apply_config(self, next_config: AcquisitionConfig) -> None:
        """Adopt a new config, rebuilding camera workers whose profile changed.

        Fixes the previous behaviour where a profile change was reported as
        "restart required" but never actually took effect on the running cameras.
        """
        prev = self.config
        self.config = next_config
        self.store.config = next_config
        if next_config.mock or prev.mock:
            return  # mock<->hardware switch is handled by a service restart
        # M3: hot-swap each worker by PUBLISHING the new worker into self.d455 /
        # self.main_rgb *before* closing the old one. A concurrent get_fresh()/
        # preview() therefore reads either the old worker (still live) or the new
        # one — never a half-closed handle. The reference swap is atomic in
        # CPython (single attribute store under the GIL), and closing the old
        # worker is independently safe: CameraWorker.close() sets its terminal
        # _closed flag under _start_lock so any in-flight read on the old handle
        # cannot resurrect it. We deliberately do not hold self._lock here; the
        # _closed flag is the cross-thread guard for the streaming path.
        streaming_changed = next_config.streaming != prev.streaming
        if streaming_changed or next_config.d455_profile != prev.d455_profile:
            old, self.d455 = self.d455, build_d455_stream(next_config)
            _safe_close(old)
        if streaming_changed or next_config.main_rgb_profile != prev.main_rgb_profile:
            old, self.main_rgb = self.main_rgb, build_main_rgb_stream(next_config)
            _safe_close(old)

    def close(self) -> None:
        """Release cameras and the H1 serial connection (service shutdown)."""
        _safe_close(self.d455)
        _safe_close(self.main_rgb)
        closer = getattr(self.h1, "close", None) or getattr(self.h1, "_reset_device", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass


def _safe_close(stream: CameraStream) -> None:
    try:
        stream.close()
    except Exception:
        pass


def _depth_unavailable_snapshot(reason: str) -> D455Snapshot:
    """A placeholder D455 snapshot for a force-degraded, spectrum-only capture.

    The sample store still writes the d455/ payload (color.jpg, depth.png/.npy,
    pointcloud PLYs, roi preview), so this must be a *valid* snapshot the writer
    can serialise without crashing — not None. We therefore hand it 1x1 (black
    color, zero depth) arrays and empty intrinsics. ``status`` is MISSING and the
    detail records why depth was unavailable; ``imu`` is marked unavailable so
    the IMU-motion quality check is skipped.
    """
    return D455Snapshot(
        status=DeviceStatus.MISSING,
        color_rgb=np.zeros((1, 1, 3), dtype=np.uint8),
        depth_mm=np.zeros((1, 1), dtype=np.uint16),
        profile={},
        intrinsics={},
        imu={"available": False},
        captured_at=utc_now_iso(),
        detail={"reason": "depth_unavailable", "error": reason},
    )


def _depth_unavailable_geometry() -> tuple[PointCloudResult, GeometryResult]:
    """An empty point cloud + ``unavailable`` geometry for a degraded capture.

    Carries the ``depth_unavailable`` warning that drives the sample to
    QualityStatus.BAD in :meth:`CaptureCoordinator._quality`.
    """
    empty = np.empty((0, 3), dtype=np.float64)
    pointcloud = PointCloudResult(
        full_points_xyz_m=empty,
        roi_points_xyz_m=empty,
        roi_mask=np.zeros((1, 1), dtype=bool),
    )
    geometry = GeometryResult(
        distance_mm=None,
        depth_valid_ratio=0.0,
        normal_camera=None,
        angle_deg=None,
        status="unavailable",
        warnings=["depth_unavailable"],
        detail={"reason": "d455 frame unavailable during capture"},
    )
    return pointcloud, geometry


def build_d455_stream(config: AcquisitionConfig) -> CameraStream:
    """Wrap the D455 device in a synchronous DirectStream (mock) or owner-thread
    CameraWorker (hardware)."""
    if config.mock:
        cam = MockD455Camera()
        return DirectStream(read=cam.snapshot, status=cam.status)
    from spectrum_acq.devices.realsense import RealSenseD455Camera

    adapter = RealSenseD455Camera(config.d455_profile)
    s = config.streaming
    return CameraWorker(
        adapter,
        name="d455",
        preview_fps=config.d455_profile.preview_fps,
        idle_timeout_s=s.idle_timeout_s,
        backoff_min_s=s.backoff_min_s,
        backoff_max_s=s.backoff_max_s,
        max_frame_age_s=s.max_frame_age_s,
        get_fresh_timeout_s=s.d455_get_fresh_timeout_s,
        reopen_attempts_before_hw_reset=s.reopen_attempts_before_hw_reset,
    )


def build_main_rgb_stream(config: AcquisitionConfig) -> CameraStream:
    if config.mock:
        cam = NullMainRgbProvider()
        return DirectStream(read=cam.capture, status=cam.status)
    adapter = V4l2MainRgbCamera(config.main_rgb_profile)
    s = config.streaming
    return CameraWorker(
        adapter,
        name="main_rgb",
        preview_fps=config.main_rgb_profile.preview_fps,
        idle_timeout_s=s.idle_timeout_s,
        backoff_min_s=s.backoff_min_s,
        backoff_max_s=s.backoff_max_s,
        max_frame_age_s=s.max_frame_age_s,
        get_fresh_timeout_s=s.main_rgb_get_fresh_timeout_s,
        reopen_attempts_before_hw_reset=s.reopen_attempts_before_hw_reset,
    )


def create_mock_coordinator(data_dir: Path | str) -> CaptureCoordinator:
    config = default_config(Path(data_dir))
    store = SampleStore(config)
    return CaptureCoordinator(
        config=config,
        h1=MockH1Spectrometer(),
        d455=build_d455_stream(config),
        main_rgb=build_main_rgb_stream(config),
        store=store,
    )


def make_sample_id() -> str:
    stamp = utc_now_iso().replace("-", "").replace(":", "").replace(".", "").replace("Z", "Z")
    suffix = f"{random.getrandbits(24):06x}"
    return f"{stamp}_{suffix}"


def max_quality(a: QualityStatus, b: QualityStatus) -> QualityStatus:
    order = {QualityStatus.GOOD: 0, QualityStatus.WARN: 1, QualityStatus.BAD: 2}
    return a if order[a] >= order[b] else b


def create_default_coordinator(config: AcquisitionConfig) -> CaptureCoordinator:
    store = SampleStore(config)
    h1: H1Spectrometer = MockH1Spectrometer() if config.mock else H1DeviceAdapter(config.h1_port)
    return CaptureCoordinator(
        config=config,
        h1=h1,
        d455=build_d455_stream(config),
        main_rgb=build_main_rgb_stream(config),
        store=store,
    )
