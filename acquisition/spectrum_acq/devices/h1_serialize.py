"""JSON serialization for H1 spectrum frames (Web UI contract)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any


def spectrum_frame_to_json(frame: Any, wavelength_start: int) -> dict[str, Any]:
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
