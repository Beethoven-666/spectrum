"""Decoding tests for PROTOCOL.md §9.2 and §9.3.

Parse the byte vectors from the protocol document and compare each field to
its documented value.
"""

from __future__ import annotations

import pytest

from h1_sdk import CieMode, ExposureMode
from h1_sdk.errors import DeviceError, ProtocolError
from h1_sdk.protocol import (
    Cmd,
    decode_cie_mode,
    decode_device_info,
    decode_exposure_mode,
    decode_u32,
    decode_wavelength_range,
    expect_status,
    parse_frame,
)


def hx(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", ""))


# ---------------------------------------------------------------------------
# Whole-frame parsing
# ---------------------------------------------------------------------------


def test_parse_device_info_frame():
    frame = hx(
        "CC 81 21 00 00 08 "
        "48 31 31 42 36 56 31 30 35 33 34 43 46 50 44 2D 31 30 30 2D 30 30 30 32 "
        "B5 0D 0A"
    )
    data_type, valid = parse_frame(frame, expected_cmd_type=Cmd.GET_DEVICE_INFO)
    assert data_type == Cmd.GET_DEVICE_INFO
    info = decode_device_info(valid)
    assert info.serial_number == "H11B6V10534CFPD-100-0002"


def test_parse_wavelength_range_frame():
    frame = hx("CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A")
    _, valid = parse_frame(frame, expected_cmd_type=Cmd.GET_WAVELENGTH_RANGE)
    wr = decode_wavelength_range(valid)
    assert wr.start == 340
    assert wr.end == 1050
    assert wr.count == 711


def test_parse_exposure_time_response():
    frame = hx("CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A")
    _, valid = parse_frame(frame, expected_cmd_type=Cmd.GET_EXPOSURE_TIME)
    assert decode_u32(valid) == 100_000


def test_parse_max_exposure_time_response():
    frame = hx("CC 81 0D 00 00 14 40 42 0F 00 FF 0D 0A")
    _, valid = parse_frame(frame, expected_cmd_type=Cmd.GET_MAX_EXPOSURE_TIME)
    assert decode_u32(valid) == 1_000_000


def test_parse_cie_mode_response():
    frame = hx("CC 81 0A 00 00 37 02 90 0D 0A")
    _, valid = parse_frame(frame, expected_cmd_type=Cmd.GET_CIE_MODE)
    assert decode_cie_mode(valid) == CieMode.Cie2015_2


def test_parse_exposure_mode_response():
    # PROTOCOL.md §3.4 0x0B
    frame = hx("CC 81 0A 00 00 0B 01 63 0D 0A")
    _, valid = parse_frame(frame, expected_cmd_type=Cmd.GET_EXPOSURE_MODE)
    assert decode_exposure_mode(valid) == ExposureMode.Auto


# ---------------------------------------------------------------------------
# Status decoding (set-style responses)
# ---------------------------------------------------------------------------


def test_set_exposure_success():
    frame = hx("CC 81 0A 00 00 0A 00 61 0D 0A")
    _, valid = parse_frame(frame, expected_cmd_type=Cmd.SET_EXPOSURE_MODE)
    # No exception on success.
    expect_status(Cmd.SET_EXPOSURE_MODE, valid)


def test_set_exposure_invalid_raises_device_error():
    frame = hx("CC 81 0A 00 00 0A 15 76 0D 0A")
    _, valid = parse_frame(frame, expected_cmd_type=Cmd.SET_EXPOSURE_MODE)
    with pytest.raises(DeviceError) as exc:
        expect_status(Cmd.SET_EXPOSURE_MODE, valid)
    assert exc.value.code == 0x15
    assert exc.value.cmd_type == Cmd.SET_EXPOSURE_MODE


def test_set_exposure_unsupported_raises_device_error():
    frame = hx("CC 81 0A 00 00 0A FF 60 0D 0A")
    _, valid = parse_frame(frame, expected_cmd_type=Cmd.SET_EXPOSURE_MODE)
    with pytest.raises(DeviceError) as exc:
        expect_status(Cmd.SET_EXPOSURE_MODE, valid)
    assert exc.value.code == 0xFF


# ---------------------------------------------------------------------------
# Negative cases — corrupt / truncated frames
# ---------------------------------------------------------------------------


def test_bad_header_raises_protocol_error():
    # Flip the first byte.
    bad = bytearray(hx("CC 81 0A 00 00 0A 00 61 0D 0A"))
    bad[0] = 0xFF
    with pytest.raises(ProtocolError, match="bad response header"):
        parse_frame(bytes(bad), expected_cmd_type=Cmd.SET_EXPOSURE_MODE)


def test_bad_footer_raises_protocol_error():
    bad = bytearray(hx("CC 81 0A 00 00 0A 00 61 0D 0A"))
    bad[-1] = 0x00
    with pytest.raises(ProtocolError, match="bad frame footer"):
        parse_frame(bytes(bad), expected_cmd_type=Cmd.SET_EXPOSURE_MODE)


def test_bad_checksum_raises_protocol_error():
    bad = bytearray(hx("CC 81 0A 00 00 0A 00 61 0D 0A"))
    bad[-3] = (bad[-3] + 1) & 0xFF
    with pytest.raises(ProtocolError, match="checksum mismatch"):
        parse_frame(bytes(bad), expected_cmd_type=Cmd.SET_EXPOSURE_MODE)


def test_truncated_frame_raises_protocol_error():
    frame = hx("CC 81 0A 00 00 0A 00")  # missing checksum + footer
    with pytest.raises(ProtocolError):
        parse_frame(frame, expected_cmd_type=Cmd.SET_EXPOSURE_MODE)


def test_total_len_mismatch_raises_protocol_error():
    # totalLen claims 11 but actual is 10.
    bad = hx("CC 81 0B 00 00 0A 00 61 0D 0A")
    with pytest.raises(ProtocolError, match="totalLen mismatch"):
        parse_frame(bad, expected_cmd_type=Cmd.SET_EXPOSURE_MODE)


def test_wrong_data_type_raises_protocol_error():
    frame = hx("CC 81 0A 00 00 0A 00 61 0D 0A")
    with pytest.raises(ProtocolError, match="dataType mismatch"):
        parse_frame(frame, expected_cmd_type=Cmd.SET_EXPOSURE_TIME)


def test_corrupt_middle_byte_breaks_checksum():
    """PROTOCOL.md §9.3 — any middle byte tampering must surface."""
    bad = bytearray(hx("CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A"))
    bad[7] ^= 0xFF  # flip a byte inside validData
    with pytest.raises(ProtocolError, match="checksum mismatch"):
        parse_frame(bytes(bad), expected_cmd_type=Cmd.GET_EXPOSURE_TIME)
