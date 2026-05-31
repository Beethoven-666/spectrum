"""Real H1 spectrometer adapter.

The adapter imports ``h1_sdk`` lazily so acquisition mock mode works on hosts
where only the service skeleton is installed.
"""

from __future__ import annotations

import time
from dataclasses import asdict

from spectrum_acq.models import DeviceStatus, H1AutoExposureConfig, utc_now_iso

from .interfaces import H1Capture, H1ExposureAttempt, H1Status


class H1DeviceAdapter:
    def __init__(self, port: str, *, timeout_s: float = 5.0) -> None:
        self.port = port
        self.timeout_s = timeout_s

    def _device(self):
        from h1_sdk import Device

        return Device(self.port, timeout=self.timeout_s)

    def status(self) -> H1Status:
        try:
            with self._device() as dev:
                info = dev.get_device_info()
                wavelength_range = dev.get_wavelength_range()
                exposure_time_us = dev.get_exposure_time_us()
                try:
                    exposure_mode = dev.get_exposure_mode().name.lower()
                except Exception:
                    exposure_mode = None
                try:
                    max_exposure_time_us = dev.get_max_exposure_time_us()
                except Exception:
                    max_exposure_time_us = None
            return H1Status(
                status=DeviceStatus.READY,
                serial_number=info.serial_number.strip(),
                wavelength_range={"start": wavelength_range.start, "end": wavelength_range.end},
                exposure_time_us=exposure_time_us,
                exposure_mode=exposure_mode,
                max_exposure_time_us=max_exposure_time_us,
                detail={"port": self.port},
            )
        except Exception as exc:  # noqa: BLE001 - hardware status should report failures
            return H1Status(
                status=DeviceStatus.ERROR,
                serial_number=None,
                wavelength_range=None,
                exposure_time_us=None,
                detail={"port": self.port, "error": str(exc)},
            )

    def capture_auto(self, config: H1AutoExposureConfig) -> H1Capture:
        from h1_sdk.types import ExposureMode

        attempts: list[H1ExposureAttempt] = []
        exposure_us = config.initial_exposure_us
        selected_index = 0
        selected_frame = None
        status = self.status()
        if status.status != DeviceStatus.READY:
            raise RuntimeError(status.detail.get("error", "H1 device is not ready"))

        with self._device() as dev:
            try:
                dev.set_exposure_mode(ExposureMode.Manual)
            except Exception:
                pass
            for idx in range(1, max(config.max_attempts, 1) + 1):
                started = utc_now_iso()
                t0 = time.monotonic()
                dev.set_exposure_time_us(int(exposure_us))
                frame = dev.capture_single(include_tm30=False)
                ended = utc_now_iso()
                exposure_status = frame.exposure_status.name.lower()
                attempt = H1ExposureAttempt(
                    attempt=idx,
                    exposure_time_us=int(exposure_us),
                    exposure_status=exposure_status,
                    started_at=started,
                    ended_at=ended,
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                )
                attempts.append(attempt)
                selected_index = idx - 1
                selected_frame = frame
                if exposure_status == "normal":
                    break
                if config.mode == "multi_exposure":
                    exposure_us = min(int(exposure_us * config.under_multiplier), config.max_exposure_us)
                    continue
                if exposure_status == "under":
                    exposure_us = min(int(exposure_us * config.under_multiplier), config.max_exposure_us)
                elif exposure_status == "over":
                    exposure_us = max(int(exposure_us * config.over_multiplier), config.min_exposure_us)

        if selected_frame is None:
            raise RuntimeError("H1 capture did not produce a frame")
        marked_attempts = [
            H1ExposureAttempt(**{**asdict(a), "selected": i == selected_index})
            for i, a in enumerate(attempts)
        ]
        wavelength_start = status.wavelength_range["start"] if status.wavelength_range else 0
        wavelengths = list(
            range(wavelength_start, wavelength_start + len(selected_frame.raw_spectrum))
        )
        return H1Capture(
            status=status,
            selected_attempt=marked_attempts[selected_index],
            attempts=marked_attempts,
            wavelengths=wavelengths,
            raw_spectrum=selected_frame.raw_spectrum,
            actual_spectrum=selected_frame.actual_spectrum,
            photometric=asdict(selected_frame.photometric),
            plant=asdict(selected_frame.plant),
            spectrum_coefficient=selected_frame.spectrum_coefficient,
        )
