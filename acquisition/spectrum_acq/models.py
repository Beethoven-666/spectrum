"""Shared data models for acquisition, storage, and API boundaries."""

from __future__ import annotations

import json
import math
import numpy as np
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal


SCHEMA_VERSION = "leaf-multimodal-sample/v1"


class QualityStatus(StrEnum):
    GOOD = "good"
    WARN = "warn"
    BAD = "bad"


class DeviceStatus(StrEnum):
    READY = "ready"
    DISABLED = "disabled"
    MISSING = "missing"
    ERROR = "error"


class CaptureState(StrEnum):
    IDLE = "idle"
    CAPTURE_REQUESTED = "capture_requested"
    CAPTURING = "capturing"
    WRITING = "writing"
    DONE = "done"
    FAILED = "failed"


ExposureModeName = Literal["conservative", "strict", "multi_exposure"]


@dataclass(frozen=True)
class Roi:
    """Normalized rectangular ROI in image coordinates."""

    x: float = 0.35
    y: float = 0.35
    width: float = 0.30
    height: float = 0.30
    source: str = "center"

    def clamp(self) -> "Roi":
        x = min(max(self.x, 0.0), 1.0)
        y = min(max(self.y, 0.0), 1.0)
        width = min(max(self.width, 0.001), 1.0 - x)
        height = min(max(self.height, 0.001), 1.0 - y)
        return Roi(x=x, y=y, width=width, height=height, source=self.source)


@dataclass(frozen=True)
class D455Profile:
    color_width: int = 640
    color_height: int = 480
    color_fps: int = 6
    depth_width: int = 640
    depth_height: int = 480
    depth_fps: int = 6
    enable_imu: bool = True
    preview_fps: float = 6.0


@dataclass(frozen=True)
class MainRgbProfile:
    device_path: str | None = None
    width: int = 640
    height: int = 480
    pixel_format: str = "MJPG"
    timeout_s: float = 10.0
    mode: str = "persistent"
    preview_fps: float = 4.0


@dataclass(frozen=True)
class StreamingConfig:
    """Tuning for the background camera owner threads (hardware mode only)."""

    idle_timeout_s: float = 15.0
    backoff_min_s: float = 0.5
    backoff_max_s: float = 30.0
    max_frame_age_s: float = 2.0
    d455_get_fresh_timeout_s: float = 8.0
    # How long a capture waits for a fresh main RGB frame before degrading to
    # ``main_rgb_missing`` (the camera is optional). A healthy warm camera
    # delivers a new frame in ~one preview period (preview_fps=4 -> ~0.25 s), so a
    # short budget is plenty AND it keeps a wedged/absent camera from adding its
    # full timeout to every capture.
    main_rgb_get_fresh_timeout_s: float = 1.0
    reopen_attempts_before_hw_reset: int = 5


@dataclass(frozen=True)
class DiskThresholds:
    warn_free_bytes: int = 2 * 1024 * 1024 * 1024
    stop_free_bytes: int = 1024 * 1024 * 1024
    allow_below_stop: bool = False


@dataclass(frozen=True)
class H1AutoExposureConfig:
    mode: ExposureModeName = "conservative"
    # Design §6 calls for a conservative strategy ("最多 2-3 次重试"). With the
    # device's native auto-exposure landing attempt #1 close to correct, a small
    # budget (1 native + up to 3 manual refinements) is plenty.
    max_attempts: int = 4
    under_multiplier: float = 1.7
    over_multiplier: float = 0.55
    min_exposure_us: int = 500
    max_exposure_us: int = 1_000_000
    initial_exposure_us: int = 50_000
    # Number of exposure levels captured (and saved) in ``multi_exposure`` mode.
    multi_exposure_steps: int = 5
    # Exposure cap for the LIVE stream only (uses the device's native auto-exposure
    # per frame). Capped at ``max_exposure_us`` (the stream uses
    # ``min(max_exposure_us, stream_max_exposure_us)``) so a long sample exposure
    # never makes the preview crawl.
    stream_max_exposure_us: int = 1_000_000


@dataclass(frozen=True)
class QualityThresholds:
    min_depth_valid_ratio: float = 0.50
    recommended_distance_min_mm: float = 180.0
    recommended_distance_max_mm: float = 800.0
    warn_angle_deg: float = 45.0
    bad_angle_deg: float = 70.0
    max_imu_delta_deg: float = 8.0


@dataclass(frozen=True)
class AcquisitionConfig:
    data_dir: Path
    mock: bool = True
    roi: Roi = field(default_factory=Roi)
    d455_profile: D455Profile = field(default_factory=D455Profile)
    disk: DiskThresholds = field(default_factory=DiskThresholds)
    h1_auto_exposure: H1AutoExposureConfig = field(default_factory=H1AutoExposureConfig)
    quality: QualityThresholds = field(default_factory=QualityThresholds)
    h1_port: str = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
    main_rgb_profile: MainRgbProfile = field(default_factory=MainRgbProfile)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    calibration_path: Path | None = None


@dataclass(frozen=True)
class DeviceSummary:
    kind: str
    status: DeviceStatus
    name: str
    serial: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StorageStatus:
    data_dir: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    warn_free_bytes: int
    stop_free_bytes: int
    status: QualityStatus


@dataclass(frozen=True)
class CaptureResult:
    sample_id: str
    sample_path: str
    quality_status: QualityStatus
    warnings: list[str]
    metadata: dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    # numpy is pervasive here (frames, intrinsics, IMU, spectra). json.dump cannot
    # serialize ndarrays or numpy scalars (np.float32/np.int64/np.bool_…), so a
    # single stray numpy value used to blow up the whole capture write with
    # "Object of type ndarray is not JSON serializable". Convert arrays to nested
    # lists and numpy scalars to plain Python, recursing so NaN/Inf floats inside
    # are still nulled by the float branch above.
    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist())
    if isinstance(value, np.generic):
        return to_jsonable(value.item())
    return value


def json_dumps(value: Any, **kwargs: Any) -> str:
    """Serialize API payloads as strict JSON (no NaN/Infinity tokens)."""
    return json.dumps(to_jsonable(value), ensure_ascii=False, allow_nan=False, **kwargs)
