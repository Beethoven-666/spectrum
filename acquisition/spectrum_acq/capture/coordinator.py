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

from spectrum_acq.config import default_config
from spectrum_acq.devices.h1 import H1DeviceAdapter
from spectrum_acq.devices.interfaces import H1Spectrometer, MainRgbProvider, RealSenseCamera
from spectrum_acq.devices.mock import MockD455Camera, MockH1Spectrometer, NullMainRgbProvider
from spectrum_acq.geometry import compute_geometry
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


class CaptureCoordinator:
    def __init__(
        self,
        *,
        config: AcquisitionConfig,
        h1: H1Spectrometer,
        d455: RealSenseCamera,
        main_rgb: MainRgbProvider,
        store: SampleStore | None = None,
    ) -> None:
        self.config = config
        self.h1 = h1
        self.d455 = d455
        self.main_rgb = main_rgb
        self.store = store or SampleStore(config)
        self._lock = threading.Lock()
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
            h1_status = self._last_h1_status or {
                "status": str(DeviceStatus.ERROR),
                "serial_number": None,
                "wavelength_range": None,
                "exposure_time_us": None,
                "exposure_mode": None,
                "max_exposure_time_us": None,
                "detail": {"error": "H1 capture or stream is busy"},
            }
        return {
            "h1": h1_status,
            "d455": to_jsonable(self.d455.status()),
            "main_rgb": to_jsonable(self.main_rgb.status()),
        }

    def stream_h1(
        self,
        *,
        include_tm30: bool = False,
        max_frames: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        if not self._lock.acquire(timeout=5.0):
            raise RuntimeError("capture busy")
        try:
            yield from self.h1.stream(
                include_tm30=include_tm30,
                max_frames=max_frames,
                config=self.config.h1_auto_exposure,
            )
        finally:
            self._lock.release()

    def _run_h1_locked(self, fn, *, timeout: float = 5.0):
        if not self._lock.acquire(timeout=timeout):
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
        if not self._lock.acquire(timeout=5.0):
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
            d455_snapshot = self.d455.snapshot()
            h1_capture = self.h1.capture_auto(h1_config)
            if (
                h1_config.mode == "strict"
                and h1_capture.selected_attempt.exposure_status != "normal"
                and not force
            ):
                raise RuntimeError(
                    f"H1 strict exposure failed: {h1_capture.selected_attempt.exposure_status}"
                )
            main_rgb_capture = self.main_rgb.capture()

            pointcloud, geometry = compute_geometry(
                d455_snapshot.depth_mm,
                d455_snapshot.intrinsics,
                active_roi,
                self.config.quality,
            )
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
        if any(w in geometry.warnings for w in ["angle_bad", "distance_unknown"]):
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

    def _set_state(self, state: CaptureState, **kwargs: Any) -> None:
        self._state = state
        self._current = {"state": state, **kwargs}


def create_mock_coordinator(data_dir: Path | str) -> CaptureCoordinator:
    config = default_config(Path(data_dir))
    store = SampleStore(config)
    return CaptureCoordinator(
        config=config,
        h1=MockH1Spectrometer(),
        d455=MockD455Camera(),
        main_rgb=NullMainRgbProvider(),
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
    if config.mock:
        h1: H1Spectrometer = MockH1Spectrometer()
        d455: RealSenseCamera = MockD455Camera()
    else:
        h1 = H1DeviceAdapter(config.h1_port)
        from spectrum_acq.devices.realsense import RealSenseD455Camera

        d455 = RealSenseD455Camera(config.d455_profile)
    return CaptureCoordinator(
        config=config,
        h1=h1,
        d455=d455,
        main_rgb=NullMainRgbProvider(),
        store=store,
    )
