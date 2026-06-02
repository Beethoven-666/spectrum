"""Mock hardware for offline acquisition development and tests."""

from __future__ import annotations

import math
import time
from typing import Any, Iterator

import numpy as np

from spectrum_acq.models import DeviceStatus, H1AutoExposureConfig, utc_now_iso

from .h1 import ladder_factors, select_index
from .interfaces import (
    D455Snapshot,
    H1Capture,
    H1ExposureAttempt,
    H1ExposureFrame,
    H1Status,
    MainRgbCapture,
)


class MockH1Spectrometer:
    """Deterministic H1 stand-in with realistic wavelength and exposure fields."""

    def __init__(self, *, scenario: str = "normal") -> None:
        self.scenario = scenario
        self.serial_number = "MOCK-H1-0001"
        self.wavelength_start = 340
        self.wavelength_end = 1050
        self._last_exposure_us = 50_000
        self._exposure_mode = "manual"
        self._max_exposure_us = 1_000_000
        self._cie_mode = "cie1931_2"
        self._working_mode = "streaming"

    def status(self) -> H1Status:
        return H1Status(
            status=DeviceStatus.READY,
            serial_number=self.serial_number,
            wavelength_range={"start": self.wavelength_start, "end": self.wavelength_end},
            exposure_time_us=self._last_exposure_us,
            exposure_mode="manual",
            max_exposure_time_us=1_000_000,
            detail={"driver": "mock"},
        )

    def capture_auto(self, config: H1AutoExposureConfig) -> H1Capture:
        multi = config.mode == "multi_exposure"
        if multi:
            records = self._multi_exposure_records(config)
            center_us = self._clamp(config.initial_exposure_us, config)
            selected_index = select_index(
                [s for _, s in records],
                center_us=center_us,
                exposure_times=[e for e, _ in records],
            )
        else:
            records = self._converge_records(config)
            selected_index = select_index([s for _, s in records])

        wavelengths = list(range(self.wavelength_start, self.wavelength_end + 1))
        coeff = 2
        now = utc_now_iso()
        attempts: list[H1ExposureAttempt] = []
        frames: list[H1ExposureFrame] = []
        for i, (exposure_us, status) in enumerate(records):
            time.sleep(0.001)
            attempts.append(
                H1ExposureAttempt(
                    attempt=i + 1,
                    exposure_time_us=int(exposure_us),
                    exposure_status=status,
                    started_at=now,
                    ended_at=utc_now_iso(),
                    duration_ms=1.0,
                    selected=i == selected_index,
                )
            )
            if multi:
                raw_i = self._spectrum(wavelengths, exposure_us)
                frames.append(
                    H1ExposureFrame(
                        attempt=i + 1,
                        exposure_time_us=int(exposure_us),
                        exposure_status=status,
                        spectrum_coefficient=coeff,
                        raw_spectrum=raw_i,
                        actual_spectrum=[v / (10.0**coeff) for v in raw_i],
                        selected=i == selected_index,
                    )
                )

        selected = attempts[selected_index]
        self._last_exposure_us = selected.exposure_time_us
        raw = self._spectrum(wavelengths, selected.exposure_time_us)
        actual = [v / (10.0**coeff) for v in raw]
        return H1Capture(
            status=self.status(),
            selected_attempt=selected,
            attempts=attempts,
            wavelengths=wavelengths,
            raw_spectrum=raw,
            actual_spectrum=actual,
            photometric={"CCT": 5100.0, "lux": 8200.0, "Ra": 91.5},
            plant={"PAR": 402.0, "PPFD": 162.0, "YPFD": 131.0},
            spectrum_coefficient=coeff,
            frames=frames,
        )

    @staticmethod
    def _clamp(value: float, config: H1AutoExposureConfig) -> int:
        return max(config.min_exposure_us, min(int(value), config.max_exposure_us))

    def _converge_records(self, config: H1AutoExposureConfig) -> list[tuple[int, str]]:
        records: list[tuple[int, str]] = []
        exposure_us: float = config.initial_exposure_us
        for status in self._status_sequence(config.max_attempts):
            records.append((self._clamp(exposure_us, config), status))
            if status == "normal":
                break
            if status == "under":
                exposure_us *= config.under_multiplier
            elif status == "over":
                exposure_us *= config.over_multiplier
        return records

    def _multi_exposure_records(self, config: H1AutoExposureConfig) -> list[tuple[int, str]]:
        records: list[tuple[int, str]] = []
        for factor in ladder_factors(config.multi_exposure_steps):
            exposure_us = self._clamp(round(config.initial_exposure_us * factor), config)
            status = "normal" if factor == 1.0 else ("under" if factor < 1.0 else "over")
            records.append((exposure_us, status))
        records.sort(key=lambda item: item[0])
        return records

    def stream(
        self,
        *,
        include_tm30: bool = False,
        max_frames: int | None = None,
        config: H1AutoExposureConfig | None = None,
    ) -> Iterator[dict[str, Any]]:
        emitted = 0
        exposure_config = config or H1AutoExposureConfig()
        while max_frames is None or emitted < max_frames:
            capture = self.capture_auto(exposure_config)
            yield h1_capture_to_stream_frame(capture, include_tm30=include_tm30)
            emitted += 1
            time.sleep(0.1)

    def device_info(self) -> dict[str, Any]:
        return {
            "serialNumber": self.serial_number,
            "wavelengthRange": {"start": self.wavelength_start, "end": self.wavelength_end},
        }

    def get_exposure(self) -> dict[str, Any]:
        return {
            "mode": self._exposure_mode,
            "timeUs": self._last_exposure_us,
            "maxTimeUs": self._max_exposure_us,
        }

    def patch_exposure(
        self,
        *,
        mode: str | None = None,
        time_us: int | None = None,
        max_time_us: int | None = None,
    ) -> dict[str, Any]:
        if mode is not None:
            self._exposure_mode = mode
        if time_us is not None:
            self._last_exposure_us = int(time_us)
        if max_time_us is not None:
            self._max_exposure_us = int(max_time_us)
        return self.get_exposure()

    def get_cie_mode(self) -> dict[str, str]:
        return {"mode": self._cie_mode}

    def set_cie_mode(self, mode_name: str) -> dict[str, str]:
        self._cie_mode = mode_name
        return self.get_cie_mode()

    def set_working_mode(self, mode: str) -> dict[str, str]:
        self._working_mode = mode
        return {"mode": mode}

    def enter_sleep(self) -> dict[str, Any]:
        return {"ok": True, "state": "sleeping"}

    def exit_sleep(self) -> dict[str, Any]:
        return {"ok": True, "state": "awake"}

    def capture_single_frame(self, *, include_tm30: bool = False) -> dict[str, Any]:
        capture = self.capture_auto(H1AutoExposureConfig())
        return h1_capture_to_stream_frame(capture, include_tm30=include_tm30)

    def upload_efficiency_curve(self, ratios: list[float]) -> dict[str, Any]:
        return {"ok": True, "count": len(ratios)}

    def verify_efficiency_curve(self) -> dict[str, Any]:
        return {"ok": True}

    def reset_efficiency_curve(self) -> dict[str, Any]:
        return {"ok": True}

    def _status_sequence(self, max_attempts: int) -> list[str]:
        if self.scenario == "under_then_normal":
            return ["under", "normal"][:max_attempts]
        if self.scenario == "over_then_normal":
            return ["over", "normal"][:max_attempts]
        if self.scenario == "always_under":
            return ["under"] * max_attempts
        if self.scenario == "always_over":
            return ["over"] * max_attempts
        return ["normal"]

    @staticmethod
    def _spectrum(wavelengths: list[int], exposure_us: int) -> list[int]:
        scale = max(exposure_us / 50_000.0, 0.1)
        out: list[int] = []
        for wl in wavelengths:
            chlorophyll_peak = 5500 * math.exp(-((wl - 680) ** 2) / (2 * 45**2))
            green_peak = 2600 * math.exp(-((wl - 550) ** 2) / (2 * 70**2))
            baseline = 500 + (wl - 340) * 1.2
            out.append(max(0, min(65535, int((baseline + chlorophyll_peak + green_peak) * scale))))
        return out


def h1_capture_to_stream_frame(capture: H1Capture, *, include_tm30: bool) -> dict[str, Any]:
    wavelength_start = capture.wavelengths[0] if capture.wavelengths else 0
    return {
        "exposureStatus": exposure_status_code(capture.selected_attempt.exposure_status),
        "exposureTimeUs": capture.selected_attempt.exposure_time_us,
        "photometric": capture.photometric,
        "blueHazard": {"Eb": 0.0},
        "nir": {"redEe": 0.0, "nirEeA": 0.0, "nirEeB": 0.0},
        "plant": capture.plant,
        "tm30": None if not include_tm30 else {},
        "spectrumCoefficient": capture.spectrum_coefficient,
        "wavelengthStart": wavelength_start,
        "rawSpectrum": capture.raw_spectrum,
        "actualSpectrum": capture.actual_spectrum,
        "wavelengths": capture.wavelengths,
    }


def exposure_status_code(status: str) -> int:
    if status == "over":
        return 1
    if status == "under":
        return 2
    return 0


class MockD455Camera:
    """Small deterministic D455-like stream used by tests and mock mode."""

    def __init__(self, *, width: int = 160, height: int = 120) -> None:
        self.width = width
        self.height = height
        self.serial = "MOCK-D455-0001"

    def status(self) -> dict[str, object]:
        return {
            "status": DeviceStatus.READY,
            "name": "Mock RealSense D455",
            "serial": self.serial,
            "profile": {
                "color": {"width": self.width, "height": self.height, "fps": 15},
                "depth": {"width": self.width, "height": self.height, "fps": 15},
            },
        }

    def snapshot(self) -> D455Snapshot:
        y, x = np.indices((self.height, self.width))
        color = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        color[..., 0] = np.clip(40 + x * 180 / max(self.width - 1, 1), 0, 255).astype(np.uint8)
        color[..., 1] = np.clip(90 + y * 120 / max(self.height - 1, 1), 0, 255).astype(np.uint8)
        color[..., 2] = 48

        cx = self.width / 2.0
        cy = self.height / 2.0
        depth = 430 + (x - cx) * 0.35 + (y - cy) * 0.15
        depth = np.clip(depth, 250, 900).astype(np.uint16)
        profile = {
            "serial": self.serial,
            "firmware": "mock",
            "color_width": self.width,
            "color_height": self.height,
            "color_fps": 15,
            "depth_width": self.width,
            "depth_height": self.height,
            "depth_fps": 15,
            "depth_scale": 0.001,
        }
        intrinsics = {
            "width": self.width,
            "height": self.height,
            "fx": float(self.width),
            "fy": float(self.width),
            "ppx": cx,
            "ppy": cy,
            "model": "pinhole-mock",
            "coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        }
        imu = {
            "available": True,
            "roll_deg": 1.2,
            "pitch_deg": -3.4,
            "yaw_deg": 18.0,
            "delta_roll_deg": 0.3,
            "delta_pitch_deg": 0.4,
            "accel_m_s2": [0.0, 0.0, 9.81],
            "gyro_rad_s": [0.0, 0.0, 0.0],
        }
        return D455Snapshot(
            status=DeviceStatus.READY,
            color_rgb=color,
            depth_mm=depth,
            profile=profile,
            intrinsics=intrinsics,
            imu=imu,
            captured_at=utc_now_iso(),
            detail={"driver": "mock"},
        )


class NullMainRgbProvider:
    """Placeholder for the future beamsplitter-aligned main RGB camera."""

    def __init__(self, *, status: DeviceStatus = DeviceStatus.MISSING) -> None:
        self._status = status

    def status(self) -> dict[str, object]:
        return {
            "status": self._status,
            "name": "Main RGB camera",
            "serial": None,
            "detail": {"driver": "null", "reason": "camera not connected yet"},
        }

    def capture(self) -> MainRgbCapture:
        return MainRgbCapture(
            status=self._status,
            captured_at=utc_now_iso(),
            image_rgb=None,
            metadata={"driver": "null", "reason": "camera not connected yet"},
        )
