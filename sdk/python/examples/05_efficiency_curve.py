"""Example 5: upload a flat unity efficiency curve, verify, then reset.

This is a destructive operation on a real device — it overwrites the
calibration. The script restores the factory default at the end.

Usage:
    python examples/05_efficiency_curve.py /dev/tty.usbserial-XYZ
"""

from __future__ import annotations

import sys

from h1_sdk import Device


def main(port: str) -> None:
    with Device(port) as dev:
        rng = dev.get_wavelength_range()
        # One ratio per spectrum point — set them all to 1.0 (identity).
        ratios = [1.0] * rng.count
        print(f"uploading {len(ratios)} ratios...")
        dev.upload_efficiency_curve(ratios)

        print("verifying and computing...")
        dev.verify_and_compute_efficiency_curve()
        print("OK")

        print("restoring factory curve...")
        dev.reset_efficiency_curve()
        print("OK")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <serial-port>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
