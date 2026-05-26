"""Example 3: stream 10 frames and print a one-line summary each.

Usage:
    python examples/03_stream.py /dev/tty.usbserial-XYZ
"""

from __future__ import annotations

import sys

from h1_sdk import Device


def main(port: str) -> None:
    with Device(port) as dev:
        for i, frame in enumerate(dev.stream(max_frames=10)):
            p = frame.photometric
            print(
                f"#{i:02d} status={frame.exposure_status.name:6s} "
                f"exposure={frame.exposure_time_us:>7d}us "
                f"CCT={p.CCT:7.1f}K Ra={p.Ra:5.2f} lux={p.lux:8.2f}"
            )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <serial-port>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
