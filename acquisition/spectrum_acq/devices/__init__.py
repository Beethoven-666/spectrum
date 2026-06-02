"""Device adapters for acquisition hardware."""

from .interfaces import (
    D455Snapshot,
    H1Capture,
    H1ExposureAttempt,
    H1Status,
    MainRgbCapture,
)
from .main_rgb import V4l2MainRgbCamera, create_main_rgb_provider, discover_main_rgb_device
from .mock import MockD455Camera, MockH1Spectrometer, NullMainRgbProvider

__all__ = [
    "D455Snapshot",
    "H1Capture",
    "H1ExposureAttempt",
    "H1Status",
    "MainRgbCapture",
    "MockD455Camera",
    "MockH1Spectrometer",
    "NullMainRgbProvider",
    "V4l2MainRgbCamera",
    "create_main_rgb_provider",
    "discover_main_rgb_device",
]
