"""Tests for the H1 auto-exposure strategy (device adapter + pure helpers).

These exercise ``H1DeviceAdapter`` against a fake SDK device so the native-auto
-first + manual-refinement logic is covered without real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from h1_sdk.types import ExposureMode, ExposureStatus

from spectrum_acq.devices.h1 import (
    H1DeviceAdapter,
    ladder_factors,
    next_exposure_time_us,
    select_index,
)
from spectrum_acq.models import H1AutoExposureConfig


# --- fake SDK device ------------------------------------------------------


@dataclass
class _Photometric:
    CCT: float = 5000.0
    lux: float = 1000.0


@dataclass
class _Plant:
    PAR: float = 1.0


@dataclass
class _Info:
    serial_number: str = "FAKE-H1-0001"


@dataclass
class _WavelengthRange:
    start: int = 340
    end: int = 342


@dataclass
class _Frame:
    exposure_time_us: int
    exposure_status: ExposureStatus
    spectrum_coefficient: int = 2
    raw_spectrum: list = field(default_factory=lambda: [100, 200, 300])
    actual_spectrum: list = field(default_factory=lambda: [1.0, 2.0, 3.0])
    photometric: _Photometric = field(default_factory=_Photometric)
    plant: _Plant = field(default_factory=_Plant)
    tm30: object | None = None


class FakeH1Device:
    """Simulates a sensor with a single 'correct' exposure window.

    In Auto mode the firmware reports ``auto_pick_us``; in Manual mode it uses
    whatever exposure was last set. Status is Under/Normal/Over relative to
    ``optimal_us`` (a 1.5x window each side).
    """

    def __init__(self, *, optimal_us: int, auto_pick_us: int, max_us: int = 5_000_000) -> None:
        self.optimal_us = optimal_us
        self.auto_pick_us = auto_pick_us
        self.max_us = max_us
        self.mode = ExposureMode.Manual
        self.exposure_us = 50_000
        self.captures: list[tuple[ExposureMode, int]] = []
        self.mode_history: list[ExposureMode] = []

    # reads
    def get_device_info(self) -> _Info:
        return _Info()

    def get_wavelength_range(self) -> _WavelengthRange:
        return _WavelengthRange()

    def get_exposure_time_us(self) -> int:
        return self.exposure_us

    def get_exposure_mode(self) -> ExposureMode:
        return self.mode

    def get_max_exposure_time_us(self) -> int:
        return self.max_us

    # writes
    def set_max_exposure_time_us(self, us: int) -> None:
        self.max_us = int(us)

    def set_exposure_mode(self, mode: ExposureMode) -> None:
        self.mode = mode
        self.mode_history.append(mode)

    def set_exposure_time_us(self, us: int) -> None:
        self.exposure_us = int(us)

    def capture_single(self, *, include_tm30: bool = False, timeout: float | None = None) -> _Frame:
        eff = self.auto_pick_us if self.mode == ExposureMode.Auto else self.exposure_us
        self.exposure_us = eff
        self.captures.append((self.mode, eff))
        return _Frame(exposure_time_us=eff, exposure_status=self._status_for(eff))

    def _status_for(self, eff: int) -> ExposureStatus:
        if eff < self.optimal_us / 1.5:
            return ExposureStatus.Under
        if eff > self.optimal_us * 1.5:
            return ExposureStatus.Over
        return ExposureStatus.Normal


def _adapter_with(device: FakeH1Device) -> H1DeviceAdapter:
    adapter = H1DeviceAdapter(port="fake")
    adapter._device = device  # bypass real serial open
    return adapter


# --- adapter behaviour ----------------------------------------------------


def test_native_auto_lands_normal_in_one_shot() -> None:
    device = FakeH1Device(optimal_us=80_000, auto_pick_us=80_000)
    adapter = _adapter_with(device)

    capture = adapter.capture_auto(H1AutoExposureConfig(mode="conservative", max_attempts=4))

    assert len(capture.attempts) == 1
    assert capture.selected_attempt.exposure_status == "normal"
    assert capture.frames == []
    # The single capture used the device's native auto-exposure.
    assert device.captures[0][0] == ExposureMode.Auto
    # The operator's mode (Manual here) is restored after capture.
    assert device.mode == ExposureMode.Manual


def test_capture_restores_operator_auto_mode() -> None:
    device = FakeH1Device(optimal_us=80_000, auto_pick_us=80_000)
    device.set_exposure_mode(ExposureMode.Auto)  # operator chose auto in the UI
    adapter = _adapter_with(device)

    adapter.capture_auto(H1AutoExposureConfig(max_attempts=4))

    assert device.mode == ExposureMode.Auto


def test_manual_refinement_converges_to_normal() -> None:
    # Native auto under-picks; manual refinement must climb to the normal window.
    device = FakeH1Device(optimal_us=50_000, auto_pick_us=8_000)
    adapter = _adapter_with(device)

    capture = adapter.capture_auto(H1AutoExposureConfig(mode="conservative", max_attempts=4))

    assert capture.selected_attempt.exposure_status == "normal"
    assert len(capture.attempts) > 1
    assert device.captures[0][0] == ExposureMode.Auto
    assert device.captures[-1][0] == ExposureMode.Manual


def test_multi_exposure_saves_a_ladder_of_frames() -> None:
    device = FakeH1Device(optimal_us=50_000, auto_pick_us=50_000)
    adapter = _adapter_with(device)

    capture = adapter.capture_auto(
        H1AutoExposureConfig(mode="multi_exposure", multi_exposure_steps=5)
    )

    assert len(capture.frames) >= 5
    assert all(f.raw_spectrum for f in capture.frames)
    # Frames are ordered by exposure and exactly one is marked selected.
    exposures = [f.exposure_time_us for f in capture.frames]
    assert exposures == sorted(exposures)
    assert sum(1 for f in capture.frames if f.selected) == 1


# --- pure helpers ---------------------------------------------------------


def test_ladder_factors_symmetric_geometric() -> None:
    assert ladder_factors(1) == [1.0]
    assert ladder_factors(5) == [0.25, 0.5, 1.0, 2.0, 4.0]


def test_select_index_prefers_normal_then_center_then_last() -> None:
    assert select_index(["under", "normal", "over"]) == 1
    assert select_index(["under", "over"]) == 1  # no normal -> last
    # no normal, but a centre hint -> nearest exposure to centre
    idx = select_index(["under", "under", "over"], center_us=100, exposure_times=[10, 90, 400])
    assert idx == 1


def test_next_exposure_bisects_once_bracketed() -> None:
    config = H1AutoExposureConfig(min_exposure_us=1, max_exposure_us=10_000_000)
    # bracketed between 40_000 (under) and 90_000 (over) -> geometric mean
    nxt = next_exposure_time_us(70_000, "over", config, under_bound=40_000, over_bound=90_000)
    assert nxt == round((40_000 * 90_000) ** 0.5)
