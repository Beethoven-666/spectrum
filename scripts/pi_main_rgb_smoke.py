#!/usr/bin/env python3
"""Minimal main RGB (UVC) smoke test for croprix-spectrum.local."""

from __future__ import annotations

import sys


def main() -> int:
    from spectrum_acq.devices.main_rgb import V4l2MainRgbCamera, discover_main_rgb_device
    from spectrum_acq.models import DeviceStatus, MainRgbProfile

    device = discover_main_rgb_device()
    print("discovered:", device or "none")
    camera = V4l2MainRgbCamera(MainRgbProfile(device_path=device))
    status = camera.status()
    print("status:", status.get("status"))
    print("detail:", status.get("detail"))
    if status.get("status") != DeviceStatus.READY:
        return 1

    capture = camera.capture()
    print("capture:", capture.status)
    print("metadata:", capture.metadata)
    if capture.image_rgb is None:
        return 2
    print("shape:", capture.image_rgb.shape, "mean:", float(capture.image_rgb.mean()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
