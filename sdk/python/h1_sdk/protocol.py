"""Pure byte-level protocol codec for the H1 spectrometer.

This module has no I/O dependencies. Everything is bytes in, bytes/typed out, so
it can be unit-tested directly against the hex vectors in PROTOCOL.md §9.

Frame layout (PROTOCOL.md §2):

    Command  (host -> device): CC 01 | totalLen[3 LE] | cmdType[1] | data[N] | checksum[1] | 0D 0A
    Response (device -> host): CC 81 | totalLen[3 LE] | dataType[1] | data[N] | checksum[1] | 0D 0A

``totalLen`` is the total frame size in bytes (header through footer), so
``totalLen = 9 + N``. ``checksum`` is the sum of every byte from the start of
the frame up to (but excluding) the checksum byte, taken mod 256.
"""

from __future__ import annotations

import struct
from dataclasses import fields, is_dataclass
from typing import List, Optional, Tuple

from .errors import DeviceError, ProtocolError
from .types import (
    BlueHazardParams,
    CieMode,
    DeviceInfo,
    ExposureMode,
    ExposureStatus,
    NirParams,
    PhotometricParams,
    PlantParams,
    SpectrumFrame,
    Tm30Params,
    WavelengthRange,
    WorkingMode,
)

# ---------------------------------------------------------------------------
# Frame constants
# ---------------------------------------------------------------------------

HEADER_CMD = b"\xCC\x01"
HEADER_RESP = b"\xCC\x81"
FOOTER = b"\x0D\x0A"

# Header (2) + totalLen (3) + cmdType (1) + data (N) + checksum (1) + footer (2) = 9 + N
FRAME_OVERHEAD = 9

# Device status codes (PROTOCOL.md §3.2)
STATUS_OK = 0x00
STATUS_INVALID = 0x15
STATUS_UNSUPPORTED = 0xFF


# ---------------------------------------------------------------------------
# Command codes (PROTOCOL.md §3.1)
# ---------------------------------------------------------------------------


class Cmd:
    STOP_CAPTURE = 0x04
    GET_DEVICE_INFO = 0x08
    SET_EXPOSURE_MODE = 0x0A
    GET_EXPOSURE_MODE = 0x0B
    SET_EXPOSURE_TIME = 0x0C
    GET_EXPOSURE_TIME = 0x0D
    GET_WAVELENGTH_RANGE = 0x0F
    SET_MAX_EXPOSURE_TIME = 0x13
    GET_MAX_EXPOSURE_TIME = 0x14
    SEND_EFFICIENCY_CURVE = 0x23
    RESET_EFFICIENCY_CURVE = 0x25
    VERIFY_EFFICIENCY_CURVE = 0x27
    CAPTURE_SINGLE_NO_TM30 = 0x32
    START_STREAM_NO_TM30 = 0x33
    CAPTURE_SINGLE_WITH_TM30 = 0x34
    START_STREAM_WITH_TM30 = 0x35
    SET_CIE_MODE = 0x36
    GET_CIE_MODE = 0x37
    ENTER_EXIT_SLEEP = 0x40
    SET_WORKING_MODE = 0x41


# Magic constant for the "start" packet of the efficiency-curve upload protocol.
EFFICIENCY_CURVE_START_MARKER = 0x04
EFFICIENCY_CURVE_MAX_PACKET_BYTES = 999
EFFICIENCY_CURVE_MAX_FLOATS_PER_PACKET = (
    EFFICIENCY_CURVE_MAX_PACKET_BYTES - FRAME_OVERHEAD
) // 4  # 247 floats


# ---------------------------------------------------------------------------
# Low-level checksum / frame helpers
# ---------------------------------------------------------------------------


def checksum(data: bytes) -> int:
    """Sum every byte of ``data`` modulo 256 (PROTOCOL.md §2.3)."""
    return sum(data) & 0xFF


def _build_frame_with_header(header: bytes, type_byte: int, payload: bytes) -> bytes:
    total_len = FRAME_OVERHEAD + len(payload)
    # totalLen is encoded as 3-byte little-endian uint24.
    total_len_bytes = struct.pack("<I", total_len)[:3]
    body = header + total_len_bytes + bytes([type_byte]) + payload
    return body + bytes([checksum(body)]) + FOOTER


def build_frame(cmd_type: int, cmd_data: bytes = b"") -> bytes:
    """Wrap a payload as a host->device command frame.

    The returned bytes are exactly what should be written to the serial port.
    """
    return _build_frame_with_header(HEADER_CMD, cmd_type, cmd_data)


def build_response_frame(data_type: int, valid_data: bytes = b"") -> bytes:
    """Wrap a payload as a device->host response frame.

    Used by tests and ``MockSerialPort`` to synthesise device replies.
    """
    return _build_frame_with_header(HEADER_RESP, data_type, valid_data)


def parse_frame(frame: bytes, expected_cmd_type: Optional[int] = None) -> Tuple[int, bytes]:
    """Parse a complete response frame and return ``(data_type, valid_data)``.

    Raises ``ProtocolError`` on any structural violation.
    """
    if len(frame) < FRAME_OVERHEAD:
        raise ProtocolError(f"frame too short: {len(frame)} bytes")
    if frame[0:2] != HEADER_RESP:
        raise ProtocolError(
            f"bad response header: expected {HEADER_RESP.hex()}, got {frame[0:2].hex()}"
        )
    if frame[-2:] != FOOTER:
        raise ProtocolError(
            f"bad frame footer: expected {FOOTER.hex()}, got {frame[-2:].hex()}"
        )

    total_len = int.from_bytes(frame[2:5], "little")
    if total_len != len(frame):
        raise ProtocolError(
            f"totalLen mismatch: header says {total_len}, actual {len(frame)}"
        )

    data_type = frame[5]
    if expected_cmd_type is not None and data_type != expected_cmd_type:
        raise ProtocolError(
            f"dataType mismatch: expected 0x{expected_cmd_type:02X}, got 0x{data_type:02X}"
        )

    expected_cs = frame[-3]
    computed_cs = checksum(frame[:-3])
    if expected_cs != computed_cs:
        raise ProtocolError(
            f"checksum mismatch: frame=0x{expected_cs:02X}, computed=0x{computed_cs:02X}"
        )

    valid_data = bytes(frame[6:-3])
    return data_type, valid_data


def expect_status(cmd_type: int, valid_data: bytes) -> None:
    """Interpret a single-byte status response and raise DeviceError on failure."""
    if len(valid_data) != 1:
        raise ProtocolError(
            f"expected 1-byte status for cmd 0x{cmd_type:02X}, got {len(valid_data)} bytes"
        )
    code = valid_data[0]
    if code == STATUS_OK:
        return
    if code == STATUS_INVALID:
        raise DeviceError(code, "invalid command", cmd_type=cmd_type)
    if code == STATUS_UNSUPPORTED:
        raise DeviceError(code, "unsupported or out of range", cmd_type=cmd_type)
    raise DeviceError(code, f"unknown status code 0x{code:02X}", cmd_type=cmd_type)


# ---------------------------------------------------------------------------
# Command builders — one per command code
# ---------------------------------------------------------------------------


def cmd_stop_capture() -> bytes:
    return build_frame(Cmd.STOP_CAPTURE)


def cmd_get_device_info() -> bytes:
    # cmdData is a single byte = expected length (0x18 == 24).
    return build_frame(Cmd.GET_DEVICE_INFO, bytes([0x18]))


def cmd_set_exposure_mode(mode: ExposureMode) -> bytes:
    return build_frame(Cmd.SET_EXPOSURE_MODE, bytes([int(mode)]))


def cmd_get_exposure_mode() -> bytes:
    return build_frame(Cmd.GET_EXPOSURE_MODE)


def cmd_set_exposure_time(us: int) -> bytes:
    return build_frame(Cmd.SET_EXPOSURE_TIME, struct.pack("<I", us))


def cmd_get_exposure_time() -> bytes:
    return build_frame(Cmd.GET_EXPOSURE_TIME)


def cmd_get_wavelength_range() -> bytes:
    return build_frame(Cmd.GET_WAVELENGTH_RANGE)


def cmd_set_max_exposure_time(us: int) -> bytes:
    return build_frame(Cmd.SET_MAX_EXPOSURE_TIME, struct.pack("<I", us))


def cmd_get_max_exposure_time() -> bytes:
    return build_frame(Cmd.GET_MAX_EXPOSURE_TIME)


def cmd_send_efficiency_curve_start() -> bytes:
    return build_frame(
        Cmd.SEND_EFFICIENCY_CURVE, bytes([EFFICIENCY_CURVE_START_MARKER])
    )


def cmd_send_efficiency_curve_chunk(floats: List[float]) -> bytes:
    """Pack a chunk of the ratio array into one frame.

    Caller is responsible for honouring the 247-floats-per-chunk limit; the
    function raises ProtocolError if the chunk is too large to fit.
    """
    if len(floats) == 0:
        raise ValueError("efficiency curve chunk must contain at least one float")
    if len(floats) > EFFICIENCY_CURVE_MAX_FLOATS_PER_PACKET:
        raise ProtocolError(
            f"efficiency curve chunk too large: {len(floats)} > "
            f"{EFFICIENCY_CURVE_MAX_FLOATS_PER_PACKET}"
        )
    data = struct.pack(f"<{len(floats)}f", *floats)
    return build_frame(Cmd.SEND_EFFICIENCY_CURVE, data)


def cmd_reset_efficiency_curve() -> bytes:
    return build_frame(Cmd.RESET_EFFICIENCY_CURVE)


def cmd_verify_efficiency_curve() -> bytes:
    return build_frame(Cmd.VERIFY_EFFICIENCY_CURVE)


def cmd_capture_single(include_tm30: bool = False) -> bytes:
    code = Cmd.CAPTURE_SINGLE_WITH_TM30 if include_tm30 else Cmd.CAPTURE_SINGLE_NO_TM30
    return build_frame(code)


def cmd_start_stream(include_tm30: bool = False) -> bytes:
    code = Cmd.START_STREAM_WITH_TM30 if include_tm30 else Cmd.START_STREAM_NO_TM30
    return build_frame(code)


def cmd_set_cie_mode(mode: CieMode) -> bytes:
    return build_frame(Cmd.SET_CIE_MODE, bytes([int(mode)]))


def cmd_get_cie_mode() -> bytes:
    return build_frame(Cmd.GET_CIE_MODE)


def cmd_enter_exit_sleep() -> bytes:
    return build_frame(Cmd.ENTER_EXIT_SLEEP)


def cmd_set_working_mode(mode: WorkingMode) -> bytes:
    return build_frame(Cmd.SET_WORKING_MODE, bytes([int(mode)]))


# ---------------------------------------------------------------------------
# Response decoders — pure: bytes (valid_data) -> typed value
# ---------------------------------------------------------------------------


def decode_device_info(valid_data: bytes) -> DeviceInfo:
    if len(valid_data) != 24:
        raise ProtocolError(
            f"device info response must be 24 bytes, got {len(valid_data)}"
        )
    # Trim trailing NULs in case the device pads short serial numbers.
    sn = valid_data.decode("ascii", errors="replace").rstrip("\x00")
    return DeviceInfo(serial_number=sn)


def decode_exposure_mode(valid_data: bytes) -> ExposureMode:
    if len(valid_data) != 1:
        raise ProtocolError(
            f"exposure mode response must be 1 byte, got {len(valid_data)}"
        )
    return ExposureMode(valid_data[0])


def decode_u32(valid_data: bytes) -> int:
    if len(valid_data) != 4:
        raise ProtocolError(
            f"u32 response must be 4 bytes, got {len(valid_data)}"
        )
    return int.from_bytes(valid_data, "little")


def decode_wavelength_range(valid_data: bytes) -> WavelengthRange:
    if len(valid_data) != 4:
        raise ProtocolError(
            f"wavelength range response must be 4 bytes, got {len(valid_data)}"
        )
    start, end = struct.unpack("<HH", valid_data)
    return WavelengthRange(start=start, end=end)


def decode_cie_mode(valid_data: bytes) -> CieMode:
    if len(valid_data) != 1:
        raise ProtocolError(
            f"CIE mode response must be 1 byte, got {len(valid_data)}"
        )
    return CieMode(valid_data[0])


# ---------------------------------------------------------------------------
# SpectrumFrame decoding (PROTOCOL.md §4 + §5)
# ---------------------------------------------------------------------------

# Photometric block layout
_PHOTO_FIELDS = tuple(f.name for f in fields(PhotometricParams))
_PHOTO_BYTES = 4 * len(_PHOTO_FIELDS)        # 188
_BLUE_BYTES = 4                              # 1 float
_NIR_BYTES = 12                              # 3 floats
_PLANT_FIELDS = tuple(f.name for f in fields(PlantParams))
_PLANT_BYTES = 4 * len(_PLANT_FIELDS)        # 64
_TM30_FLOATS = 614
_TM30_BYTES = 4 * _TM30_FLOATS               # 2456

# Fixed offsets (the part before raw_spectrum)
_HEADER_FIXED_BYTES = 1 + 4                  # exposureStatus + exposureTimeUs
_PRE_COEFF_BYTES_NO_TM30 = (
    _HEADER_FIXED_BYTES + _PHOTO_BYTES + _BLUE_BYTES + _NIR_BYTES + _PLANT_BYTES
)  # 273

_PRE_COEFF_BYTES_WITH_TM30 = _PRE_COEFF_BYTES_NO_TM30 + _TM30_BYTES  # 2729


def _decode_photometric(data: bytes) -> PhotometricParams:
    if len(data) != _PHOTO_BYTES:
        raise ProtocolError(
            f"photometric block must be {_PHOTO_BYTES} bytes, got {len(data)}"
        )
    values = struct.unpack(f"<{len(_PHOTO_FIELDS)}f", data)
    return PhotometricParams(**dict(zip(_PHOTO_FIELDS, values)))


def _decode_plant(data: bytes) -> PlantParams:
    if len(data) != _PLANT_BYTES:
        raise ProtocolError(
            f"plant block must be {_PLANT_BYTES} bytes, got {len(data)}"
        )
    values = struct.unpack(f"<{len(_PLANT_FIELDS)}f", data)
    return PlantParams(**dict(zip(_PLANT_FIELDS, values)))


def _decode_tm30(data: bytes) -> Tm30Params:
    if len(data) != _TM30_BYTES:
        raise ProtocolError(
            f"TM30 block must be {_TM30_BYTES} bytes, got {len(data)}"
        )
    floats = struct.unpack(f"<{_TM30_FLOATS}f", data)
    ref_spec = list(floats[0:401])
    eab = list(floats[401:500])
    rf = floats[500]
    rg = floats[501]
    chroma = list(floats[502:518])
    hue = list(floats[518:534])
    fidelity = list(floats[534:550])
    test_pairs_flat = floats[550:582]
    ref_pairs_flat = floats[582:614]
    ces_test = [
        (test_pairs_flat[2 * i], test_pairs_flat[2 * i + 1]) for i in range(16)
    ]
    ces_ref = [
        (ref_pairs_flat[2 * i], ref_pairs_flat[2 * i + 1]) for i in range(16)
    ]
    return Tm30Params(
        referenceSpectrum=ref_spec,
        Eab=eab,
        Rf=rf,
        Rg=rg,
        chromaShift=chroma,
        hueShift=hue,
        colorFidelity=fidelity,
        cesAbTest=ces_test,
        cesAbReference=ces_ref,
    )


def decode_spectrum_frame(valid_data: bytes, include_tm30: bool) -> SpectrumFrame:
    """Decode the validData portion of a 0x32/0x33/0x34/0x35 response."""
    pre_coeff = _PRE_COEFF_BYTES_WITH_TM30 if include_tm30 else _PRE_COEFF_BYTES_NO_TM30
    if len(valid_data) < pre_coeff + 2:
        raise ProtocolError(
            f"spectrum frame too short: {len(valid_data)} bytes "
            f"(need at least {pre_coeff + 2})"
        )

    spectrum_block_bytes = len(valid_data) - pre_coeff - 2
    if spectrum_block_bytes % 2 != 0:
        raise ProtocolError(
            f"spectrum block must be a multiple of 2 bytes, got {spectrum_block_bytes}"
        )
    m = spectrum_block_bytes // 2

    cursor = 0
    exposure_status = ExposureStatus(valid_data[cursor])
    cursor += 1
    exposure_time_us = int.from_bytes(valid_data[cursor : cursor + 4], "little")
    cursor += 4

    photometric = _decode_photometric(valid_data[cursor : cursor + _PHOTO_BYTES])
    cursor += _PHOTO_BYTES

    blue_value = struct.unpack("<f", valid_data[cursor : cursor + _BLUE_BYTES])[0]
    blue = BlueHazardParams(Eb=blue_value)
    cursor += _BLUE_BYTES

    nir_values = struct.unpack("<3f", valid_data[cursor : cursor + _NIR_BYTES])
    nir = NirParams(redEe=nir_values[0], nirEeA=nir_values[1], nirEeB=nir_values[2])
    cursor += _NIR_BYTES

    plant = _decode_plant(valid_data[cursor : cursor + _PLANT_BYTES])
    cursor += _PLANT_BYTES

    tm30: Optional[Tm30Params] = None
    if include_tm30:
        tm30 = _decode_tm30(valid_data[cursor : cursor + _TM30_BYTES])
        cursor += _TM30_BYTES

    coefficient = struct.unpack("<h", valid_data[cursor : cursor + 2])[0]
    cursor += 2

    raw = list(struct.unpack(f"<{m}H", valid_data[cursor : cursor + 2 * m]))

    return SpectrumFrame(
        exposure_status=exposure_status,
        exposure_time_us=exposure_time_us,
        photometric=photometric,
        blue_hazard=blue,
        nir=nir,
        plant=plant,
        spectrum_coefficient=coefficient,
        raw_spectrum=raw,
        tm30=tm30,
    )


# ---------------------------------------------------------------------------
# Stream parser — pulls one complete frame off a byte buffer
# ---------------------------------------------------------------------------


def try_extract_frame(buffer: bytearray) -> Optional[bytes]:
    """Inspect ``buffer`` for one full response frame, consume it, return it.

    Returns None if not enough bytes yet. Raises ProtocolError if the buffer
    is corrupted (bad header that we can't realign — caller may choose to
    discard and retry).
    """
    # Skip junk until we see a valid response header.
    while len(buffer) >= 2 and buffer[:2] != HEADER_RESP:
        del buffer[0]
    if len(buffer) < 5:
        return None
    total_len = int.from_bytes(buffer[2:5], "little")
    if total_len < FRAME_OVERHEAD or total_len > 1_000_000:
        # Header looked good but totalLen is nonsense — drop one byte and retry.
        del buffer[0]
        raise ProtocolError(f"implausible totalLen={total_len}; resynchronising")
    if len(buffer) < total_len:
        return None
    frame = bytes(buffer[:total_len])
    del buffer[:total_len]
    return frame
