#!/usr/bin/env python3
"""Minimal H1 smoke test for croprix-spectrum.local."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    args = parser.parse_args()

    from h1_sdk import Device

    with Device(args.port, timeout=5.0) as dev:
        info = dev.get_device_info()
        wavelength_range = dev.get_wavelength_range()
        exposure_mode = dev.get_exposure_mode()
        max_exposure_time_us = dev.get_max_exposure_time_us()
        frame = dev.capture_single()
    print("serial:", info.serial_number.strip())
    print("wavelength_range:", wavelength_range.start, wavelength_range.end)
    print("exposure_mode:", exposure_mode.name)
    print("max_exposure_time_us:", max_exposure_time_us)
    print("exposure_status:", frame.exposure_status.name)
    print("exposure_time_us:", frame.exposure_time_us)
    print("raw_points:", len(frame.raw_spectrum))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
