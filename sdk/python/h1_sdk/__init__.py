"""H1 spectrometer Python SDK.

Top-level public API. Importing from any other submodule is supported but
unstable across minor versions.
"""

from __future__ import annotations

from .device import AsyncDevice, Device
from .errors import DeviceError, H1Error, H1TimeoutError, ProtocolError
from .mock import MockSerialPort
from .types import (
    BlueHazardParams,
    CieMode,
    DeviceInfo,
    ExposureMode,
    ExposureStatus,
    NirParams,
    PhotometricParams,
    PlantParams,
    SpectrumFrame,
    Tm30Params,
    WavelengthRange,
    WorkingMode,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Device
    "Device",
    "AsyncDevice",
    # Mock for tests / offline dev
    "MockSerialPort",
    # Data types
    "SpectrumFrame",
    "PhotometricParams",
    "BlueHazardParams",
    "NirParams",
    "PlantParams",
    "Tm30Params",
    "WavelengthRange",
    "DeviceInfo",
    # Enums
    "ExposureMode",
    "WorkingMode",
    "CieMode",
    "ExposureStatus",
    # Errors
    "H1Error",
    "ProtocolError",
    "H1TimeoutError",
    "DeviceError",
]
