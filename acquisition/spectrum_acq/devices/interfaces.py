"""Typed boundaries between hardware adapters and the capture coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from spectrum_acq.models import DeviceStatus, H1AutoExposureConfig


@dataclass(frozen=True)
class H1Status:
    status: DeviceStatus
    serial_number: str | None
    wavelength_range: dict[str, int] | None
    exposure_time_us: int | None
    exposure_mode: str | None = None
    max_exposure_time_us: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class H1ExposureAttempt:
    attempt: int
    exposure_time_us: int
    exposure_status: str
    started_at: str
    ended_at: str
    duration_ms: float
    selected: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class H1Capture:
    status: H1Status
    selected_attempt: H1ExposureAttempt
    attempts: list[H1ExposureAttempt]
    wavelengths: list[int]
    raw_spectrum: list[int]
    actual_spectrum: list[float]
    photometric: dict[str, float]
    plant: dict[str, float]
    spectrum_coefficient: int


@dataclass(frozen=True)
class D455Snapshot:
    status: DeviceStatus
    color_rgb: np.ndarray
    depth_mm: np.ndarray
    profile: dict[str, Any]
    intrinsics: dict[str, Any]
    imu: dict[str, Any]
    captured_at: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MainRgbCapture:
    status: DeviceStatus
    captured_at: str
    image_rgb: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class H1Spectrometer(Protocol):
    def status(self) -> H1Status: ...

    def capture_auto(self, config: H1AutoExposureConfig) -> H1Capture: ...


class RealSenseCamera(Protocol):
    def status(self) -> dict[str, Any]: ...

    def snapshot(self) -> D455Snapshot: ...


class MainRgbProvider(Protocol):
    def status(self) -> dict[str, Any]: ...

    def capture(self) -> MainRgbCapture: ...
