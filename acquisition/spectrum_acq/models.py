"""Shared data models for acquisition, storage, and API boundaries."""

from __future__ import annotations

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
    color_fps: int = 15
    depth_width: int = 640
    depth_height: int = 480
    depth_fps: int = 15


@dataclass(frozen=True)
class DiskThresholds:
    warn_free_bytes: int = 2 * 1024 * 1024 * 1024
    stop_free_bytes: int = 1024 * 1024 * 1024
    allow_below_stop: bool = False


@dataclass(frozen=True)
class H1AutoExposureConfig:
    mode: ExposureModeName = "conservative"
    max_attempts: int = 3
    under_multiplier: float = 1.7
    over_multiplier: float = 0.55
    min_exposure_us: int = 500
    max_exposure_us: int = 1_000_000
    initial_exposure_us: int = 50_000


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
    return value
