"""Example 1: connect to an H1 device and print metadata.

Usage:
    python examples/01_device_info.py /dev/tty.usbserial-XYZ
"""

from __future__ import annotations

import sys

from h1_sdk import Device


def main(port: str) -> None:
    with Device(port) as dev:
        info = dev.get_device_info()
        rng = dev.get_wavelength_range()
        print(f"Serial number      : {info.serial_number}")
        print(f"Wavelength range   : {rng.start}-{rng.end} nm")
        print(f"Wavelength points  : {rng.count}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <serial-port>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
