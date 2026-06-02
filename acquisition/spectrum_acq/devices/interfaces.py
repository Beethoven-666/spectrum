"""Typed boundaries between hardware adapters and the capture coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterator
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
class H1ExposureFrame:
    """Full spectrum for one exposure attempt.

    Only populated in ``multi_exposure`` mode, where every exposure level is
    saved for offline study (design §6). In the other modes the capture only
    keeps the selected frame's spectrum on :class:`H1Capture` directly.
    """

    attempt: int
    exposure_time_us: int
    exposure_status: str
    spectrum_coefficient: int
    raw_spectrum: list[int]
    actual_spectrum: list[float]
    selected: bool = False


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
    # Per-exposure spectra, populated only in ``multi_exposure`` mode.
    frames: list[H1ExposureFrame] = field(default_factory=list)


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

    def stream(
        self,
        *,
        include_tm30: bool = False,
        max_frames: int | None = None,
        config: H1AutoExposureConfig | None = None,
    ) -> Iterator[dict[str, Any]]: ...

    def device_info(self) -> dict[str, Any]: ...

    def get_exposure(self) -> dict[str, Any]: ...

    def patch_exposure(
        self,
        *,
        mode: str | None = None,
        time_us: int | None = None,
        max_time_us: int | None = None,
    ) -> dict[str, Any]: ...

    def get_cie_mode(self) -> dict[str, str]: ...

    def set_cie_mode(self, mode_name: str) -> dict[str, str]: ...

    def set_working_mode(self, mode: str) -> dict[str, str]: ...

    def enter_sleep(self) -> dict[str, Any]: ...

    def exit_sleep(self) -> dict[str, Any]: ...

    def capture_single_frame(self, *, include_tm30: bool = False) -> dict[str, Any]: ...

    def upload_efficiency_curve(self, ratios: list[float]) -> dict[str, Any]: ...

    def verify_efficiency_curve(self) -> dict[str, Any]: ...

    def reset_efficiency_curve(self) -> dict[str, Any]: ...


class RealSenseCamera(Protocol):
    def status(self) -> dict[str, Any]: ...

    def snapshot(self) -> D455Snapshot: ...


class MainRgbProvider(Protocol):
    def status(self) -> dict[str, Any]: ...

    def capture(self) -> MainRgbCapture: ...


class CameraStream(Protocol):
    """A background-owned camera the coordinator and routes read from.

    Implemented by ``CameraWorker`` (hardware, threaded + self-healing) and
    ``DirectStream`` (mock, synchronous). ``get_fresh`` returns a frame captured
    after the call (for sample capture); ``preview`` returns the latest cached
    frame or ``None`` (for HTTP previews); ``status`` returns the device status
    merged with a ``health`` sub-dict.
    """

    def status(self) -> dict[str, Any]: ...

    def get_fresh(self, timeout: float | None = None) -> Any: ...

    def preview(self) -> Any | None: ...

    def note_demand(self) -> None: ...

    def close(self) -> None: ...
