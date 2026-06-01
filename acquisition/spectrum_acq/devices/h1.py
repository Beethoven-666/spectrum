"""Real H1 spectrometer adapter with a persistent serial connection.

The adapter imports ``h1_sdk`` lazily so acquisition mock mode works on hosts
where only the service skeleton is installed.
"""

from __future__ import annotations

import time
from dataclasses import asdict, replace
from typing import Any, Iterator

from spectrum_acq.models import DeviceStatus, H1AutoExposureConfig, utc_now_iso

from .h1_cie import cie_mode_from_name, cie_mode_name
from .h1_serialize import spectrum_frame_to_json
from .interfaces import H1Capture, H1ExposureAttempt, H1Status


class H1DeviceAdapter:
    def __init__(self, port: str, *, timeout_s: float = 5.0) -> None:
        self.port = port
        self.timeout_s = timeout_s
        self._device: Any | None = None

    def _ensure_device(self) -> Any:
        if self._device is not None:
            return self._device
        from h1_sdk import Device

        self._device = Device(self.port, timeout=self.timeout_s)
        return self._device

    def _reset_device(self) -> None:
        if self._device is None:
            return
        try:
            self._device.close()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass
        self._device = None

    def status(self) -> H1Status:
        try:
            return self._status_from_device(self._ensure_device())
        except Exception as exc:  # noqa: BLE001 - hardware status should report failures
            self._reset_device()
            return H1Status(
                status=DeviceStatus.ERROR,
                serial_number=None,
                wavelength_range=None,
                exposure_time_us=None,
                detail={"port": self.port, "error": str(exc)},
            )

    def _call_device(self, fn):
        try:
            return fn(self._ensure_device())
        except Exception:
            self._reset_device()
            raise

    def device_info(self) -> dict[str, Any]:
        def work(dev: Any) -> dict[str, Any]:
            info = dev.get_device_info()
            wavelength_range = dev.get_wavelength_range()
            return {
                "serialNumber": info.serial_number.strip(),
                "wavelengthRange": {"start": wavelength_range.start, "end": wavelength_range.end},
            }

        return self._call_device(work)

    def get_exposure(self) -> dict[str, Any]:
        from h1_sdk.types import ExposureMode

        dev = self._ensure_device()
        mode = dev.get_exposure_mode()
        return {
            "mode": "auto" if mode == ExposureMode.Auto else "manual",
            "timeUs": dev.get_exposure_time_us(),
            "maxTimeUs": dev.get_max_exposure_time_us(),
        }

    def patch_exposure(
        self,
        *,
        mode: str | None = None,
        time_us: int | None = None,
        max_time_us: int | None = None,
    ) -> dict[str, Any]:
        from h1_sdk.types import ExposureMode

        dev = self._ensure_device()
        if mode is not None:
            dev.set_exposure_mode(ExposureMode.Auto if mode == "auto" else ExposureMode.Manual)
        if time_us is not None:
            dev.set_exposure_time_us(int(time_us))
        if max_time_us is not None:
            dev.set_max_exposure_time_us(int(max_time_us))
        return self.get_exposure()

    def get_cie_mode(self) -> dict[str, str]:
        dev = self._ensure_device()
        return {"mode": cie_mode_name(dev.get_cie_mode())}

    def set_cie_mode(self, mode_name: str) -> dict[str, str]:
        mode = cie_mode_from_name(mode_name)
        dev = self._ensure_device()
        dev.set_cie_mode(mode)
        return self.get_cie_mode()

    def set_working_mode(self, mode: str) -> dict[str, str]:
        from h1_sdk.types import WorkingMode

        dev = self._ensure_device()
        working = WorkingMode.Trigger if mode == "trigger" else WorkingMode.Streaming
        dev.set_working_mode(working)
        return {"mode": mode}

    def enter_sleep(self) -> dict[str, Any]:
        self._ensure_device().enter_sleep()
        return {"ok": True, "state": "sleeping"}

    def exit_sleep(self) -> dict[str, Any]:
        self._ensure_device().exit_sleep()
        return {"ok": True, "state": "awake"}

    def capture_single_frame(self, *, include_tm30: bool = False) -> dict[str, Any]:
        def work(dev: Any) -> dict[str, Any]:
            wavelength_range = dev.get_wavelength_range()
            exposure_us = dev.get_exposure_time_us()
            frame = dev.capture_single(
                include_tm30=include_tm30,
                timeout=capture_timeout_s(exposure_us, self.timeout_s),
            )
            return spectrum_frame_to_json(frame, wavelength_range.start)

        return self._call_device(work)

    def upload_efficiency_curve(self, ratios: list[float]) -> dict[str, Any]:
        dev = self._ensure_device()
        dev.upload_efficiency_curve(ratios)
        return {"ok": True, "count": len(ratios)}

    def verify_efficiency_curve(self) -> dict[str, Any]:
        self._ensure_device().verify_and_compute_efficiency_curve()
        return {"ok": True}

    def reset_efficiency_curve(self) -> dict[str, Any]:
        self._ensure_device().reset_efficiency_curve()
        return {"ok": True}

    def capture_auto(self, config: H1AutoExposureConfig) -> H1Capture:
        dev = self._ensure_device()
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
        dev = self._ensure_device()
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
            yield spectrum_frame_to_json(frame, wavelength_range.start)


def spectrum_frame_to_stream_payload(frame: Any, wavelength_start: int) -> dict[str, Any]:
    """Backward-compatible alias."""
    return spectrum_frame_to_json(frame, wavelength_start)


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
