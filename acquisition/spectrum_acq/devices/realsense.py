"""RealSense D455 adapter.

This module is imported only when mock mode is disabled. It deliberately keeps
``pyrealsense2`` optional so regular development and tests do not require the
Raspberry Pi hardware stack.
"""

from __future__ import annotations

import math
from threading import Lock
from typing import Any

import numpy as np

from spectrum_acq.devices.interfaces import D455Snapshot
from spectrum_acq.models import D455Profile, DeviceStatus, utc_now_iso


class RealSenseD455Camera:
    def __init__(self, profile: D455Profile) -> None:
        self.profile = profile
        try:
            import pyrealsense2 as rs  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "pyrealsense2 is required for real D455 capture; use mock mode until it is installed"
            ) from exc
        self.rs = rs
        self.pipeline = rs.pipeline()
        self.align = rs.align(rs.stream.color)
        self._pipeline_profile = None
        self._depth_scale = None
        self._imu_requested = False
        self._imu_error: str | None = None
        self._lock = Lock()

    def status(self) -> dict[str, object]:
        ctx = self.rs.context()
        devices = ctx.query_devices()
        if len(devices) == 0:
            return {
                "status": DeviceStatus.MISSING,
                "name": "Intel RealSense D455",
                "serial": None,
                "detail": {"error": "no RealSense devices found"},
            }
        dev = devices[0]
        return {
            "status": DeviceStatus.READY,
            "name": _safe_info(self.rs, dev, self.rs.camera_info.name),
            "serial": _safe_info(self.rs, dev, self.rs.camera_info.serial_number),
            "firmware": _safe_info(self.rs, dev, self.rs.camera_info.firmware_version),
            "profile": {
                "color_width": self.profile.color_width,
                "color_height": self.profile.color_height,
                "color_fps": self.profile.color_fps,
                "depth_width": self.profile.depth_width,
                "depth_height": self.profile.depth_height,
                "depth_fps": self.profile.depth_fps,
            },
        }

    def snapshot(self) -> D455Snapshot:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> D455Snapshot:
        try:
            return self._read_snapshot_locked()
        except RuntimeError as exc:
            if "cannot be called before start" not in str(exc):
                raise
            self._reset_pipeline_locked()
            return self._read_snapshot_locked()

    def _read_snapshot_locked(self) -> D455Snapshot:
        self._ensure_started()
        frames = self.pipeline.wait_for_frames(5000)
        aligned = self.align.process(frames)
        color_frame = aligned.get_color_frame()
        depth_frame = aligned.get_depth_frame()
        if not color_frame or not depth_frame:
            raise RuntimeError("D455 did not provide both color and depth frames")

        color = np.asanyarray(color_frame.get_data()).copy()
        depth_raw = np.asanyarray(depth_frame.get_data()).copy()
        depth_mm = np.rint(depth_raw.astype(np.float64) * float(self._depth_scale) * 1000.0).astype(np.uint16)
        intrinsics = _intrinsics_to_dict(color_frame.profile.as_video_stream_profile().intrinsics)
        profile = self._profile_dict(color_frame, depth_frame)
        imu = self._imu_from_frames(frames)
        return D455Snapshot(
            status=DeviceStatus.READY,
            color_rgb=color,
            depth_mm=depth_mm,
            profile=profile,
            intrinsics=intrinsics,
            imu=imu,
            captured_at=utc_now_iso(),
            detail={"driver": "pyrealsense2"},
        )

    def close(self) -> None:
        with self._lock:
            self._stop_pipeline_locked()

    def _reset_pipeline_locked(self) -> None:
        self._stop_pipeline_locked()
        self.pipeline = self.rs.pipeline()

    def _stop_pipeline_locked(self) -> None:
        if self._pipeline_profile is None:
            return
        try:
            self.pipeline.stop()
        except Exception:
            pass
        self._pipeline_profile = None
        self._depth_scale = None

    def _ensure_started(self) -> None:
        if self._pipeline_profile is not None:
            return
        config = self._stream_config(include_imu=True)
        imu_requested = True
        try:
            self._pipeline_profile = self.pipeline.start(config)
            self._imu_requested = imu_requested
            self._imu_error = None
        except Exception as exc:
            # Some Raspberry Pi / Ubuntu images expose the D455 IMU through
            # Linux IIO nodes that are not readable by the normal user. Depth
            # and color are still useful, so keep the capture path alive and
            # report the missing IMU in metadata instead of failing the sample.
            self.pipeline = self.rs.pipeline()
            fallback_config = self._stream_config(include_imu=False)
            try:
                self._pipeline_profile = self.pipeline.start(fallback_config)
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"failed to start D455 pipeline with IMU ({exc}) "
                    f"or without IMU ({fallback_exc})"
                ) from fallback_exc
            self._imu_requested = False
            self._imu_error = str(exc)

        depth_sensor = self._pipeline_profile.get_device().first_depth_sensor()
        self._depth_scale = depth_sensor.get_depth_scale()

    def _stream_config(self, *, include_imu: bool) -> Any:
        config = self.rs.config()
        config.enable_stream(
            self.rs.stream.depth,
            self.profile.depth_width,
            self.profile.depth_height,
            self.rs.format.z16,
            self.profile.depth_fps,
        )
        config.enable_stream(
            self.rs.stream.color,
            self.profile.color_width,
            self.profile.color_height,
            self.rs.format.rgb8,
            self.profile.color_fps,
        )
        if include_imu:
            config.enable_stream(self.rs.stream.accel)
            config.enable_stream(self.rs.stream.gyro)
        return config

    def _profile_dict(self, color_frame: Any, depth_frame: Any) -> dict[str, Any]:
        device = self._pipeline_profile.get_device()
        return {
            "serial": _safe_info(self.rs, device, self.rs.camera_info.serial_number),
            "firmware": _safe_info(self.rs, device, self.rs.camera_info.firmware_version),
            "color_width": color_frame.get_width(),
            "color_height": color_frame.get_height(),
            "color_fps": self.profile.color_fps,
            "depth_width": depth_frame.get_width(),
            "depth_height": depth_frame.get_height(),
            "depth_fps": self.profile.depth_fps,
            "depth_scale": self._depth_scale,
        }

    def _imu_from_frames(self, frames: Any) -> dict[str, Any]:
        imu: dict[str, Any] = {"available": False, "enabled": bool(self._imu_requested)}
        if self._imu_error:
            imu["error"] = self._imu_error
        for stream_name, stream in [("accel", self.rs.stream.accel), ("gyro", self.rs.stream.gyro)]:
            frame = frames.first_or_default(stream)
            if not frame:
                continue
            motion = frame.as_motion_frame().get_motion_data()
            imu["available"] = True
            imu[f"{stream_name}_timestamp_ms"] = frame.get_timestamp()
            imu[f"{stream_name}_xyz"] = [motion.x, motion.y, motion.z]
        accel = imu.get("accel_xyz")
        if isinstance(accel, list) and len(accel) == 3:
            ax, ay, az = [float(v) for v in accel]
            imu["roll_deg"] = math.degrees(math.atan2(ay, az))
            imu["pitch_deg"] = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
            imu["delta_roll_deg"] = 0.0
            imu["delta_pitch_deg"] = 0.0
        return imu


def _intrinsics_to_dict(intrinsics: Any) -> dict[str, Any]:
    return {
        "width": intrinsics.width,
        "height": intrinsics.height,
        "fx": intrinsics.fx,
        "fy": intrinsics.fy,
        "ppx": intrinsics.ppx,
        "ppy": intrinsics.ppy,
        "model": str(intrinsics.model),
        "coeffs": list(intrinsics.coeffs),
    }


def _safe_info(rs: Any, device: Any, key: Any) -> str | None:
    try:
        if device.supports(key):
            return device.get_info(key)
    except Exception:
        return None
    return None
