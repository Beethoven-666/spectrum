"""Encoding tests for PROTOCOL.md §9.1.

Each command-builder must produce byte-perfect output against the hex vectors
copied directly from the protocol document.
"""

from __future__ import annotations

import pytest

from h1_sdk import CieMode, ExposureMode, WorkingMode
from h1_sdk.protocol import (
    cmd_capture_single,
    cmd_enter_exit_sleep,
    cmd_get_cie_mode,
    cmd_get_device_info,
    cmd_get_exposure_mode,
    cmd_get_exposure_time,
    cmd_get_max_exposure_time,
    cmd_get_wavelength_range,
    cmd_reset_efficiency_curve,
    cmd_send_efficiency_curve_start,
    cmd_set_cie_mode,
    cmd_set_exposure_mode,
    cmd_set_exposure_time,
    cmd_set_max_exposure_time,
    cmd_set_working_mode,
    cmd_start_stream,
    cmd_stop_capture,
    cmd_verify_efficiency_curve,
)


def hx(s: str) -> bytes:
    """Strip whitespace and decode a hex literal."""
    return bytes.fromhex(s.replace(" ", ""))


@pytest.mark.parametrize(
    "actual,expected_hex,label",
    [
        (cmd_stop_capture(), "CC 01 09 00 00 04 DA 0D 0A", "StopCapture"),
        (cmd_get_device_info(), "CC 01 0A 00 00 08 18 F7 0D 0A", "GetDeviceInfo"),
        (
            cmd_set_exposure_mode(ExposureMode.Manual),
            "CC 01 0A 00 00 0A 00 E1 0D 0A",
            "SetExposureMode(Manual)",
        ),
        (
            cmd_set_exposure_mode(ExposureMode.Auto),
            "CC 01 0A 00 00 0A 01 E2 0D 0A",
            "SetExposureMode(Auto)",
        ),
        (cmd_get_exposure_mode(), "CC 01 09 00 00 0B E1 0D 0A", "GetExposureMode"),
        (
            cmd_set_exposure_time(100_000),
            "CC 01 0D 00 00 0C A0 86 01 00 0D 0D 0A",
            "SetExposureTime(100000)",
        ),
        (cmd_get_exposure_time(), "CC 01 09 00 00 0D E3 0D 0A", "GetExposureTime"),
        (cmd_get_wavelength_range(), "CC 01 09 00 00 0F E5 0D 0A", "GetWavelengthRange"),
        (
            cmd_set_max_exposure_time(5_000_000),
            "CC 01 0D 00 00 13 40 4B 4C 00 C4 0D 0A",
            "SetMaxExposureTime(5000000)",
        ),
        (cmd_get_max_exposure_time(), "CC 01 09 00 00 14 EA 0D 0A", "GetMaxExposureTime"),
        (
            cmd_send_efficiency_curve_start(),
            "CC 01 0A 00 00 23 04 FE 0D 0A",
            "SendEfficiencyCurveStart",
        ),
        (
            cmd_verify_efficiency_curve(),
            "CC 01 09 00 00 27 FD 0D 0A",
            "VerifyEfficiencyCurve",
        ),
        (
            cmd_reset_efficiency_curve(),
            "CC 01 09 00 00 25 FB 0D 0A",
            "ResetEfficiencyCurve",
        ),
        (
            cmd_capture_single(include_tm30=False),
            "CC 01 09 00 00 32 08 0D 0A",
            "CaptureSingleNoTm30",
        ),
        (
            cmd_start_stream(include_tm30=False),
            "CC 01 09 00 00 33 09 0D 0A",
            "StartStreamNoTm30",
        ),
        (
            cmd_capture_single(include_tm30=True),
            "CC 01 09 00 00 34 0A 0D 0A",
            "CaptureSingleWithTm30",
        ),
        (
            cmd_start_stream(include_tm30=True),
            "CC 01 09 00 00 35 0B 0D 0A",
            "StartStreamWithTm30",
        ),
        (
            cmd_set_cie_mode(CieMode.Cie2015_2),
            "CC 01 0A 00 00 36 02 0F 0D 0A",
            "SetCieMode(Cie2015_2)",
        ),
        (cmd_get_cie_mode(), "CC 01 09 00 00 37 0D 0D 0A", "GetCieMode"),
        (cmd_enter_exit_sleep(), "CC 01 09 00 00 40 16 0D 0A", "EnterExitSleep"),
        (
            cmd_set_working_mode(WorkingMode.Trigger),
            "CC 01 0A 00 00 41 01 19 0D 0A",
            "SetWorkingMode(Trigger)",
        ),
    ],
)
def test_command_encoding_matches_protocol_doc(actual, expected_hex, label):
    expected = hx(expected_hex)
    assert actual == expected, (
        f"{label}: produced {actual.hex().upper()}, expected {expected.hex().upper()}"
    )


def test_set_working_mode_streaming_extra_vector():
    """PROTOCOL.md §3.4 additionally documents the streaming variant."""
    assert cmd_set_working_mode(WorkingMode.Streaming) == hx(
        "CC 01 0A 00 00 41 00 18 0D 0A"
    )
