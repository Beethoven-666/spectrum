"""``h1`` command-line tool.

Subcommands (matching spec §10):

* ``h1 info`` — print device info + wavelength range
* ``h1 capture [--tm30] [--port ...]`` — single capture, summarised
* ``h1 stream [--count N] [--tm30] [--csv file]`` — continuous capture
* ``h1 set-exposure <us>`` / ``h1 get-exposure``
* ``h1 set-mode <auto|manual>`` / ``h1 get-mode``
* ``h1 reset-curve``
"""

from __future__ import annotations

import argparse
import csv
import sys
from typing import List, Optional, Sequence

from . import __version__
from .device import Device
from .errors import H1Error
from .types import ExposureMode


def _add_port_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--port",
        required=True,
        help="serial port path, e.g. /dev/tty.usbserial-XYZ or COM3",
    )
    p.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="baud rate (default 115200)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="serial read timeout in seconds (default 1.0)",
    )


def _open(args: argparse.Namespace) -> Device:
    return Device(args.port, baudrate=args.baud, timeout=args.timeout)


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def _cmd_info(args: argparse.Namespace) -> int:
    with _open(args) as dev:
        info = dev.get_device_info()
        rng = dev.get_wavelength_range()
        print(f"Serial number     : {info.serial_number}")
        print(f"Wavelength range  : {rng.start}-{rng.end} nm  ({rng.count} points)")
    return 0


def _summarise_frame(frame, tm30: bool) -> str:
    p = frame.photometric
    lines = [
        f"exposureStatus    : {frame.exposure_status.name}",
        f"exposureTimeUs    : {frame.exposure_time_us}",
        f"CCT               : {p.CCT:.1f} K",
        f"Ra                : {p.Ra:.2f}",
        f"lux               : {p.lux:.2f}",
        f"PPFD              : {frame.plant.PPFD:.2f}",
        f"spectrumCoeff     : {frame.spectrum_coefficient}",
        f"rawSpectrum len   : {len(frame.raw_spectrum)}",
    ]
    if tm30 and frame.tm30 is not None:
        lines.append(f"TM30 Rf/Rg        : {frame.tm30.Rf:.2f} / {frame.tm30.Rg:.2f}")
    return "\n".join(lines)


def _cmd_capture(args: argparse.Namespace) -> int:
    with _open(args) as dev:
        frame = dev.capture_single(include_tm30=args.tm30)
        print(_summarise_frame(frame, args.tm30))
    return 0


def _cmd_stream(args: argparse.Namespace) -> int:
    writer: Optional[csv.writer] = None
    csv_file = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="")
        writer = csv.writer(csv_file)
    try:
        with _open(args) as dev:
            wl = dev.get_wavelength_range()
            if writer is not None:
                header = ["frame_idx", "exposure_status", "exposure_time_us", "CCT", "Ra", "lux"]
                header += [f"raw_{nm}nm" for nm in range(wl.start, wl.end + 1)]
                writer.writerow(header)
            for i, frame in enumerate(
                dev.stream(include_tm30=args.tm30, max_frames=args.count)
            ):
                p = frame.photometric
                if writer is not None:
                    row: List[object] = [
                        i,
                        frame.exposure_status.name,
                        frame.exposure_time_us,
                        f"{p.CCT:.1f}",
                        f"{p.Ra:.2f}",
                        f"{p.lux:.2f}",
                    ]
                    row.extend(frame.raw_spectrum)
                    writer.writerow(row)
                else:
                    print(
                        f"#{i:03d} status={frame.exposure_status.name} "
                        f"CCT={p.CCT:7.1f}K Ra={p.Ra:5.2f} lux={p.lux:8.2f}"
                    )
    finally:
        if csv_file is not None:
            csv_file.close()
    return 0


def _cmd_set_exposure(args: argparse.Namespace) -> int:
    with _open(args) as dev:
        dev.set_exposure_time_us(args.us)
        print(f"OK; exposure set to {args.us} us")
    return 0


def _cmd_get_exposure(args: argparse.Namespace) -> int:
    with _open(args) as dev:
        us = dev.get_exposure_time_us()
        print(f"{us}")
    return 0


def _cmd_set_mode(args: argparse.Namespace) -> int:
    mode = ExposureMode.Manual if args.mode == "manual" else ExposureMode.Auto
    with _open(args) as dev:
        dev.set_exposure_mode(mode)
        print(f"OK; exposure mode set to {mode.name}")
    return 0


def _cmd_get_mode(args: argparse.Namespace) -> int:
    with _open(args) as dev:
        mode = dev.get_exposure_mode()
        print(mode.name)
    return 0


def _cmd_reset_curve(args: argparse.Namespace) -> int:
    with _open(args) as dev:
        dev.reset_efficiency_curve()
        print("OK; efficiency curve reset to factory default")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="h1",
        description="H1 spectrometer command-line tool",
    )
    parser.add_argument("--version", action="version", version=f"h1 {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_info = sub.add_parser("info", help="print device info and wavelength range")
    _add_port_arg(p_info)
    p_info.set_defaults(func=_cmd_info)

    p_cap = sub.add_parser("capture", help="single-frame capture")
    _add_port_arg(p_cap)
    p_cap.add_argument("--tm30", action="store_true", help="include TM30 data")
    p_cap.set_defaults(func=_cmd_capture)

    p_stream = sub.add_parser("stream", help="continuous capture")
    _add_port_arg(p_stream)
    p_stream.add_argument("--count", type=int, default=10, help="number of frames")
    p_stream.add_argument("--tm30", action="store_true", help="include TM30 data")
    p_stream.add_argument("--csv", type=str, help="write frames to CSV file")
    p_stream.set_defaults(func=_cmd_stream)

    p_setexp = sub.add_parser("set-exposure", help="set manual exposure time (us)")
    _add_port_arg(p_setexp)
    p_setexp.add_argument("us", type=int)
    p_setexp.set_defaults(func=_cmd_set_exposure)

    p_getexp = sub.add_parser("get-exposure", help="get current exposure time (us)")
    _add_port_arg(p_getexp)
    p_getexp.set_defaults(func=_cmd_get_exposure)

    p_setmode = sub.add_parser("set-mode", help="set exposure mode")
    _add_port_arg(p_setmode)
    p_setmode.add_argument("mode", choices=["auto", "manual"])
    p_setmode.set_defaults(func=_cmd_set_mode)

    p_getmode = sub.add_parser("get-mode", help="get exposure mode")
    _add_port_arg(p_getmode)
    p_getmode.set_defaults(func=_cmd_get_mode)

    p_reset = sub.add_parser("reset-curve", help="restore efficiency curve to factory")
    _add_port_arg(p_reset)
    p_reset.set_defaults(func=_cmd_reset_curve)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except H1Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - top-level CLI catch
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
