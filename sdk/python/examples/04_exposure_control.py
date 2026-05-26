"""Example 4: cycle exposure modes and compare a single capture in each.

Usage:
    python examples/04_exposure_control.py /dev/tty.usbserial-XYZ
"""

from __future__ import annotations

import sys

from h1_sdk import Device, ExposureMode


def main(port: str) -> None:
    with Device(port) as dev:
        # Manual: pin a known exposure time and check the device echoes it back.
        manual_us = 100_000  # 100 ms
        dev.set_exposure_mode(ExposureMode.Manual)
        dev.set_exposure_time_us(manual_us)
        assert dev.get_exposure_mode() == ExposureMode.Manual
        assert dev.get_exposure_time_us() == manual_us

        frame_manual = dev.capture_single()
        print(
            f"manual  exposure={frame_manual.exposure_time_us}us "
            f"status={frame_manual.exposure_status.name} "
            f"CCT={frame_manual.photometric.CCT:.1f}K"
        )

        # Auto: device picks the exposure time.
        dev.set_exposure_mode(ExposureMode.Auto)
        assert dev.get_exposure_mode() == ExposureMode.Auto

        frame_auto = dev.capture_single()
        print(
            f"auto    exposure={frame_auto.exposure_time_us}us "
            f"status={frame_auto.exposure_status.name} "
            f"CCT={frame_auto.photometric.CCT:.1f}K"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <serial-port>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
