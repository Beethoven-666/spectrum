"""RealSense D455 adapter (pure device I/O).

This module is imported only when mock mode is disabled. It deliberately keeps
``pyrealsense2`` optional so regular development and tests do not require the
Raspberry Pi hardware stack.

The adapter is a *single-shot* device driver: ``open`` starts a fresh pipeline,
``read`` returns exactly one snapshot (raising on any failure), and ``close``
stops the pipeline. All caching, retry, throttling, and self-healing live in
:class:`spectrum_acq.devices.streaming.CameraWorker`, which owns this adapter on
a single thread.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from spectrum_acq.devices.interfaces import D455Snapshot
from spectrum_acq.models import D455Profile, DeviceStatus, utc_now_iso


class RealSenseD455Camera:
    #: The pipeline blocks in ``read`` at its configured fps, so the worker must
    #: not sleep-throttle on top of it (that would back up librealsense's queue).
    paces_itself = True

    def __init__(
        self,
        profile: D455Profile,
        *,
        enable_imu: bool | None = None,
        frame_timeout_ms: int = 3000,
        frame_deadline_s: float = 3.0,
    ) -> None:
        self.profile = profile
        self._enable_imu = profile.enable_imu if enable_imu is None else enable_imu
        try:
            import pyrealsense2 as rs  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "pyrealsense2 is required for real D455 capture; use mock mode until it is installed"
            ) from exc
        self.rs = rs
        self.align = rs.align(rs.stream.color)
        self._frame_timeout_ms = frame_timeout_ms
        self._frame_deadline_s = frame_deadline_s

        self.pipeline: Any | None = None
        self._pipeline_profile: Any | None = None
        self._depth_scale: float | None = None
        self._imu_requested = False
        self._imu_error: str | None = None
        self._previous_imu_angles: tuple[float, float] | None = None
        self._latest_motion_frames: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ adapter

    def open(self) -> None:
        """Start a fresh pipeline, falling back to no-IMU if the IMU won't start."""
        self.close()
        self.pipeline = self.rs.pipeline()
        try:
            self._pipeline_profile = self.pipeline.start(self._stream_config(include_imu=self._enable_imu))
            self._imu_requested = self._enable_imu
            self._imu_error = None
        except Exception as exc:
            if not self._enable_imu:
                raise
            # Some Raspberry Pi / Ubuntu images expose the D455 IMU through Linux
            # IIO nodes that are not readable by the normal user. Depth and color
            # are still useful, so keep the capture path alive and report the
            # missing IMU in metadata instead of failing.
            self.pipeline = self.rs.pipeline()
            self._latest_motion_frames = {}
            try:
                self._pipeline_profile = self.pipeline.start(self._stream_config(include_imu=False))
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"failed to start D455 pipeline with IMU ({exc}) or without IMU ({fallback_exc})"
                ) from fallback_exc
            self._imu_requested = False
            self._imu_error = str(exc)

        depth_sensor = self._pipeline_profile.get_device().first_depth_sensor()
        self._depth_scale = depth_sensor.get_depth_scale()

    def read(self) -> D455Snapshot:
        pipeline = self.pipeline
        if pipeline is None or self._pipeline_profile is None:
            raise RuntimeError("D455 pipeline is not started")
        frames = self._wait_for_color_depth(pipeline)
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
        accel = imu.get("accel_xyz")
        if isinstance(accel, list) and len(accel) == 3:
            ax, ay, az = [float(v) for v in accel]
            roll_deg = math.degrees(math.atan2(ay, az))
            pitch_deg = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
            imu["roll_deg"] = roll_deg
            imu["pitch_deg"] = pitch_deg
            if self._previous_imu_angles is not None:
                prev_roll, prev_pitch = self._previous_imu_angles
                imu["delta_roll_deg"] = roll_deg - prev_roll
                imu["delta_pitch_deg"] = pitch_deg - prev_pitch
            else:
                imu["delta_roll_deg"] = 0.0
                imu["delta_pitch_deg"] = 0.0
            self._previous_imu_angles = (roll_deg, pitch_deg)
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
        """Stop the pipeline. Safe to call from another thread to unblock ``read``."""
        pipeline = self.pipeline
        started = self._pipeline_profile is not None
        self._pipeline_profile = None
        self._depth_scale = None
        self._latest_motion_frames = {}
        if pipeline is not None and started:
            try:
                pipeline.stop()
            except Exception:
                pass

    def describe(self) -> dict[str, Any]:
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
            "imu": {"enabled": bool(self._imu_requested), "error": self._imu_error},
            "profile": {
                "color_width": self.profile.color_width,
                "color_height": self.profile.color_height,
                "color_fps": self.profile.color_fps,
                "depth_width": self.profile.depth_width,
                "depth_height": self.profile.depth_height,
                "depth_fps": self.profile.depth_fps,
            },
        }

    def hardware_reset(self) -> None:
        """Last-resort recovery requested by the worker after repeated failures."""
        try:
            for dev in self.rs.context().query_devices():
                dev.hardware_reset()
                break
        except Exception:
            pass

    # ----------------------------------------------------------------- internals

    def _wait_for_color_depth(self, pipeline: Any) -> Any:
        """Return the next frameset containing both color and depth.

        With the IMU enabled, ``wait_for_frames`` can return motion-only
        framesets; skip those (caching their motion data) until a color+depth
        frameset arrives or the short deadline elapses. ``wait_for_frames``
        itself raises on its own timeout / a stopped pipeline, which the worker
        turns into a reconnect.
        """
        deadline = time.monotonic() + self._frame_deadline_s
        while True:
            frames = pipeline.wait_for_frames(self._frame_timeout_ms)
            self._cache_motion_frames(frames)
            if frames.get_color_frame() and frames.get_depth_frame():
                return frames
            if time.monotonic() >= deadline:
                raise RuntimeError("D455 did not provide color/depth frames in time")

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
        self._cache_motion_frames(frames)
        for stream_name in ("accel", "gyro"):
            cached = self._latest_motion_frames.get(stream_name)
            if not cached:
                continue
            imu["available"] = True
            imu[f"{stream_name}_timestamp_ms"] = cached["timestamp_ms"]
            imu[f"{stream_name}_xyz"] = cached["xyz"]
        return imu

    def _cache_motion_frames(self, frames: Any) -> None:
        for stream_name, stream in [("accel", self.rs.stream.accel), ("gyro", self.rs.stream.gyro)]:
            frame = frames.first_or_default(stream)
            if not frame:
                continue
            motion = frame.as_motion_frame().get_motion_data()
            self._latest_motion_frames[stream_name] = {
                "timestamp_ms": frame.get_timestamp(),
                "xyz": [motion.x, motion.y, motion.z],
            }


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
