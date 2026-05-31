"""Real H1 spectrometer adapter.

The adapter imports ``h1_sdk`` lazily so acquisition mock mode works on hosts
where only the service skeleton is installed.
"""

from __future__ import annotations

import time
from dataclasses import asdict, replace
from typing import Any, Iterator

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
                return self._status_from_device(dev)
        except Exception as exc:  # noqa: BLE001 - hardware status should report failures
            return H1Status(
                status=DeviceStatus.ERROR,
                serial_number=None,
                wavelength_range=None,
                exposure_time_us=None,
                detail={"port": self.port, "error": str(exc)},
            )

    def capture_auto(self, config: H1AutoExposureConfig) -> H1Capture:
        with self._device() as dev:
            status = self._status_from_device(dev)
            if status.status != DeviceStatus.READY:
                raise RuntimeError(status.detail.get("error", "H1 device is not ready"))
            return self._capture_auto_with_device(dev, config, status=status)

    def _status_from_device(self, dev: Any) -> H1Status:
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

    def _capture_auto_with_device(
        self,
        dev: Any,
        config: H1AutoExposureConfig,
        *,
        status: H1Status | None = None,
    ) -> H1Capture:
        from h1_sdk.types import ExposureMode

        active_status = status or self._status_from_device(dev)
        attempts: list[H1ExposureAttempt] = []
        selected_index = 0
        selected_frame = None
        effective_config = config

        try:
            dev.set_max_exposure_time_us(config.max_exposure_us)
        except Exception:
            pass
        try:
            device_max_exposure_us = int(dev.get_max_exposure_time_us())
            if device_max_exposure_us > 0:
                effective_config = replace(
                    config,
                    max_exposure_us=min(config.max_exposure_us, device_max_exposure_us),
                )
        except Exception:
            pass
        try:
            dev.set_exposure_mode(ExposureMode.Manual)
        except Exception:
            pass

        exposure_us = clamp_exposure_us(
            active_status.exposure_time_us or effective_config.initial_exposure_us,
            effective_config,
        )
        max_attempts = max(effective_config.max_attempts, 1)

        for idx in range(1, max_attempts + 1):
            started = utc_now_iso()
            t0 = time.monotonic()
            dev.set_exposure_time_us(int(exposure_us))
            frame = dev.capture_single(
                include_tm30=False,
                timeout=capture_timeout_s(exposure_us, self.timeout_s),
            )
            ended = utc_now_iso()
            actual_exposure_us = int(frame.exposure_time_us)
            exposure_status = frame.exposure_status.name.lower()
            attempt = H1ExposureAttempt(
                attempt=idx,
                exposure_time_us=actual_exposure_us,
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

            next_exposure_us = next_exposure_time_us(
                actual_exposure_us,
                exposure_status,
                effective_config,
            )
            if next_exposure_us == exposure_us:
                break
            exposure_us = next_exposure_us

        # Keep the device parked at the selected exposure so a following stream
        # uses the converged value instead of the stale startup value.
        try:
            dev.set_exposure_time_us(int(attempts[selected_index].exposure_time_us))
        except Exception:
            pass

        if selected_frame is None:
            raise RuntimeError("H1 capture did not produce a frame")
        marked_attempts = [
            H1ExposureAttempt(**{**asdict(a), "selected": i == selected_index})
            for i, a in enumerate(attempts)
        ]
        wavelength_start = active_status.wavelength_range["start"] if active_status.wavelength_range else 0
        wavelengths = list(
            range(wavelength_start, wavelength_start + len(selected_frame.raw_spectrum))
        )
        final_status = self._status_from_device(dev)
        return H1Capture(
            status=final_status,
            selected_attempt=marked_attempts[selected_index],
            attempts=marked_attempts,
            wavelengths=wavelengths,
            raw_spectrum=selected_frame.raw_spectrum,
            actual_spectrum=selected_frame.actual_spectrum,
            photometric=asdict(selected_frame.photometric),
            plant=asdict(selected_frame.plant),
            spectrum_coefficient=selected_frame.spectrum_coefficient,
        )

    def stream(
        self,
        *,
        include_tm30: bool = False,
        max_frames: int | None = None,
        config: H1AutoExposureConfig | None = None,
    ) -> Iterator[dict[str, Any]]:
        with self._device() as dev:
            wavelength_range = dev.get_wavelength_range()
            frame_timeout = self.timeout_s
            if config is not None:
                self._capture_auto_with_device(dev, config)
                frame_timeout = capture_timeout_s(config.max_exposure_us, self.timeout_s)
            for frame in dev.stream(
                include_tm30=include_tm30,
                max_frames=max_frames,
                frame_timeout=frame_timeout,
            ):
                yield spectrum_frame_to_stream_payload(frame, wavelength_range.start)


def spectrum_frame_to_stream_payload(frame: Any, wavelength_start: int) -> dict[str, Any]:
    raw_spectrum = list(frame.raw_spectrum)
    actual_spectrum = list(frame.actual_spectrum)
    return {
        "exposureStatus": int(frame.exposure_status),
        "exposureTimeUs": frame.exposure_time_us,
        "photometric": asdict(frame.photometric),
        "blueHazard": asdict(frame.blue_hazard),
        "nir": asdict(frame.nir),
        "plant": asdict(frame.plant),
        "tm30": asdict(frame.tm30) if frame.tm30 is not None else None,
        "spectrumCoefficient": frame.spectrum_coefficient,
        "wavelengthStart": wavelength_start,
        "rawSpectrum": raw_spectrum,
        "actualSpectrum": actual_spectrum,
        "wavelengths": [wavelength_start + i for i in range(len(raw_spectrum))],
    }


def clamp_exposure_us(value: int, config: H1AutoExposureConfig) -> int:
    return max(config.min_exposure_us, min(int(value), config.max_exposure_us))


def capture_timeout_s(exposure_us: int, base_timeout_s: float) -> float:
    return max(base_timeout_s, (int(exposure_us) / 1_000_000.0) + 10.0)


def next_exposure_time_us(
    exposure_us: int,
    exposure_status: str,
    config: H1AutoExposureConfig,
) -> int:
    if exposure_status == "under":
        return clamp_exposure_us(int(exposure_us * config.under_multiplier), config)
    if exposure_status == "over":
        return clamp_exposure_us(int(exposure_us * config.over_multiplier), config)
    return clamp_exposure_us(exposure_us, config)
