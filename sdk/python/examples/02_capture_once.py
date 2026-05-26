"""Example 2: single-frame capture and pretty-print the highlights.

Usage:
    python examples/02_capture_once.py /dev/tty.usbserial-XYZ
"""

from __future__ import annotations

import sys

from h1_sdk import Device


def main(port: str) -> None:
    with Device(port) as dev:
        frame = dev.capture_single()
        p = frame.photometric
        print(f"exposureStatus  : {frame.exposure_status.name}")
        print(f"exposureTimeUs  : {frame.exposure_time_us}")
        print(f"CCT             : {p.CCT:.1f} K")
        print(f"Ra              : {p.Ra:.2f}")
        print(f"lux             : {p.lux:.2f}")
        print(f"DUV             : {p.DUV:.4f}")
        print(f"Lp (peak nm)    : {p.Lp:.1f}")
        print(f"raw spectrum    : {len(frame.raw_spectrum)} points, "
              f"coefficient={frame.spectrum_coefficient}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <serial-port>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
