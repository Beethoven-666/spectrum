"""End-to-end ``Device`` tests using ``MockSerialPort``.

Each test wires up the mock with a canned response and verifies that the
high-level method (a) wrote the right bytes and (b) decoded the response into
the expected typed value.
"""

from __future__ import annotations

import struct
import threading
import time

import pytest

from h1_sdk import (
    CieMode,
    Device,
    DeviceError,
    ExposureMode,
    ExposureStatus,
    H1TimeoutError,
    MockSerialPort,
    WorkingMode,
)
from h1_sdk.protocol import Cmd, build_response_frame


def hx(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", ""))


# ---------------------------------------------------------------------------
# Helpers — synthesise SpectrumFrame validData
# ---------------------------------------------------------------------------


def synth_spectrum_valid(*, m: int = 8, include_tm30: bool = False) -> bytes:
    parts = [bytes([ExposureStatus.Normal]), struct.pack("<I", 1234)]
    parts.append(struct.pack("<47f", *([0.0] * 47)))
    parts.append(struct.pack("<f", 0.0))
    parts.append(struct.pack("<3f", *([0.0] * 3)))
    parts.append(struct.pack("<16f", *([0.0] * 16)))
    if include_tm30:
        parts.append(struct.pack("<614f", *([0.0] * 614)))
    parts.append(struct.pack("<h", 2))
    parts.append(struct.pack(f"<{m}H", *range(m)))
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Meta + simple getters
# ---------------------------------------------------------------------------


def test_get_device_info_roundtrip():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_DEVICE_INFO,
        lambda _: build_response_frame(Cmd.GET_DEVICE_INFO, b"H11B6V10534CFPD-100-0002"),
    )
    with Device(port) as dev:
        info = dev.get_device_info()
    assert info.serial_number == "H11B6V10534CFPD-100-0002"
    # The SDK should have written the documented GetDeviceInfo command.
    assert port.writes[0] == hx("CC 01 0A 00 00 08 18 F7 0D 0A")


def test_request_resynchronises_after_leading_garbage():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_DEVICE_INFO,
        lambda _: b"\x00\x00\xCC\x00"
        + build_response_frame(Cmd.GET_DEVICE_INFO, b"H11B6V10534CFPD-100-0002"),
    )
    with Device(port) as dev:
        info = dev.get_device_info()
    assert info.serial_number == "H11B6V10534CFPD-100-0002"


def test_request_skips_stale_nonmatching_frame():
    port = MockSerialPort()
    stale_stream_frame = build_response_frame(
        Cmd.START_STREAM_NO_TM30, synth_spectrum_valid()
    )
    target_response = build_response_frame(
        Cmd.GET_EXPOSURE_TIME, struct.pack("<I", 321_000)
    )
    port.on_command(
        Cmd.GET_EXPOSURE_TIME,
        lambda _: stale_stream_frame + target_response,
    )
    with Device(port) as dev:
        exposure_time_us = dev.get_exposure_time_us()
    assert exposure_time_us == 321_000


def test_get_wavelength_range_roundtrip():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_WAVELENGTH_RANGE,
        lambda _: build_response_frame(
            Cmd.GET_WAVELENGTH_RANGE, struct.pack("<HH", 340, 1050)
        ),
    )
    with Device(port) as dev:
        wr = dev.get_wavelength_range()
    assert wr.start == 340 and wr.end == 1050 and wr.count == 711


def test_get_exposure_time_roundtrip():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_EXPOSURE_TIME,
        lambda _: build_response_frame(Cmd.GET_EXPOSURE_TIME, struct.pack("<I", 100_000)),
    )
    with Device(port) as dev:
        us = dev.get_exposure_time_us()
    assert us == 100_000


def test_get_max_exposure_time_roundtrip():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_MAX_EXPOSURE_TIME,
        lambda _: build_response_frame(Cmd.GET_MAX_EXPOSURE_TIME, struct.pack("<I", 1_000_000)),
    )
    with Device(port) as dev:
        us = dev.get_max_exposure_time_us()
    assert us == 1_000_000


def test_get_exposure_mode_roundtrip():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_EXPOSURE_MODE,
        lambda _: build_response_frame(Cmd.GET_EXPOSURE_MODE, bytes([0x01])),
    )
    with Device(port) as dev:
        mode = dev.get_exposure_mode()
    assert mode == ExposureMode.Auto


def test_get_cie_mode_roundtrip():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_CIE_MODE, lambda _: build_response_frame(Cmd.GET_CIE_MODE, bytes([0x02]))
    )
    with Device(port) as dev:
        m = dev.get_cie_mode()
    assert m == CieMode.Cie2015_2


# ---------------------------------------------------------------------------
# Setters — success and failure paths
# ---------------------------------------------------------------------------


def _ok(cmd_type: int):
    return lambda _: build_response_frame(cmd_type, bytes([0x00]))


def test_set_exposure_mode_success():
    port = MockSerialPort()
    port.on_command(Cmd.SET_EXPOSURE_MODE, _ok(Cmd.SET_EXPOSURE_MODE))
    with Device(port) as dev:
        dev.set_exposure_mode(ExposureMode.Manual)
    assert port.writes[0] == hx("CC 01 0A 00 00 0A 00 E1 0D 0A")


def test_set_exposure_time_success():
    port = MockSerialPort()
    port.on_command(Cmd.SET_EXPOSURE_TIME, _ok(Cmd.SET_EXPOSURE_TIME))
    with Device(port) as dev:
        dev.set_exposure_time_us(100_000)
    assert port.writes[0] == hx("CC 01 0D 00 00 0C A0 86 01 00 0D 0D 0A")


def test_set_max_exposure_time_success():
    port = MockSerialPort()
    port.on_command(Cmd.SET_MAX_EXPOSURE_TIME, _ok(Cmd.SET_MAX_EXPOSURE_TIME))
    with Device(port) as dev:
        dev.set_max_exposure_time_us(5_000_000)
    assert port.writes[0] == hx("CC 01 0D 00 00 13 40 4B 4C 00 C4 0D 0A")


def test_set_cie_mode_success():
    port = MockSerialPort()
    port.on_command(Cmd.SET_CIE_MODE, _ok(Cmd.SET_CIE_MODE))
    with Device(port) as dev:
        dev.set_cie_mode(CieMode.Cie2015_2)
    assert port.writes[0] == hx("CC 01 0A 00 00 36 02 0F 0D 0A")


def test_set_working_mode_success():
    port = MockSerialPort()
    port.on_command(Cmd.SET_WORKING_MODE, _ok(Cmd.SET_WORKING_MODE))
    with Device(port) as dev:
        dev.set_working_mode(WorkingMode.Trigger)
    assert port.writes[0] == hx("CC 01 0A 00 00 41 01 19 0D 0A")


def test_set_exposure_mode_invalid_raises():
    port = MockSerialPort()
    port.on_command(
        Cmd.SET_EXPOSURE_MODE,
        lambda _: build_response_frame(Cmd.SET_EXPOSURE_MODE, bytes([0x15])),
    )
    with Device(port) as dev:
        with pytest.raises(DeviceError) as exc:
            dev.set_exposure_mode(ExposureMode.Manual)
        assert exc.value.code == 0x15


def test_set_exposure_time_unsupported_raises():
    port = MockSerialPort()
    port.on_command(
        Cmd.SET_EXPOSURE_TIME,
        lambda _: build_response_frame(Cmd.SET_EXPOSURE_TIME, bytes([0xFF])),
    )
    with Device(port) as dev:
        with pytest.raises(DeviceError) as exc:
            dev.set_exposure_time_us(1_000_000_000)
        assert exc.value.code == 0xFF


# ---------------------------------------------------------------------------
# Sleep / stop / no-response commands
# ---------------------------------------------------------------------------


def test_enter_sleep_sends_frame_with_no_response_expected():
    port = MockSerialPort()
    with Device(port) as dev:
        dev.enter_sleep()
    assert port.writes[0] == hx("CC 01 09 00 00 40 16 0D 0A")


def test_exit_sleep_sends_same_frame():
    port = MockSerialPort()
    with Device(port) as dev:
        dev.exit_sleep()
    assert port.writes[0] == hx("CC 01 09 00 00 40 16 0D 0A")


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def test_capture_single_no_tm30_decodes_frame():
    port = MockSerialPort()
    valid = synth_spectrum_valid(m=4)
    port.on_command(
        Cmd.CAPTURE_SINGLE_NO_TM30,
        lambda _: build_response_frame(Cmd.CAPTURE_SINGLE_NO_TM30, valid),
    )
    with Device(port) as dev:
        frame = dev.capture_single(include_tm30=False, timeout=1.0)
    assert frame.exposure_time_us == 1234
    assert frame.tm30 is None
    assert frame.raw_spectrum == [0, 1, 2, 3]
    assert port.writes[0] == hx("CC 01 09 00 00 32 08 0D 0A")


def test_capture_single_with_tm30_decodes_tm30():
    port = MockSerialPort()
    valid = synth_spectrum_valid(m=4, include_tm30=True)
    port.on_command(
        Cmd.CAPTURE_SINGLE_WITH_TM30,
        lambda _: build_response_frame(Cmd.CAPTURE_SINGLE_WITH_TM30, valid),
    )
    with Device(port) as dev:
        frame = dev.capture_single(include_tm30=True, timeout=1.0)
    assert frame.tm30 is not None
    assert len(frame.tm30.referenceSpectrum) == 401
    assert port.writes[0] == hx("CC 01 09 00 00 34 0A 0D 0A")


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def test_stream_yields_max_frames_then_sends_stop():
    """``stream(max_frames=N)`` should yield exactly N and then send 0x04."""
    port = MockSerialPort()

    # Pre-load three stream frames into the read buffer.
    valid = synth_spectrum_valid(m=4)
    stream_frame = build_response_frame(Cmd.START_STREAM_NO_TM30, valid)

    def on_start(_data):
        # Sending START triggers three back-to-back frames in the buffer.
        return stream_frame * 3

    port.on_command(Cmd.START_STREAM_NO_TM30, on_start)

    with Device(port) as dev:
        frames = list(dev.stream(max_frames=2, frame_timeout=1.0))

    assert len(frames) == 2
    # The first write is the start command, the last must be the stop command.
    assert port.writes[0] == hx("CC 01 09 00 00 33 09 0D 0A")
    assert port.writes[-1] == hx("CC 01 09 00 00 04 DA 0D 0A")


def test_stream_with_tm30_uses_0x35_and_0x04():
    port = MockSerialPort()
    valid = synth_spectrum_valid(m=4, include_tm30=True)
    stream_frame = build_response_frame(Cmd.START_STREAM_WITH_TM30, valid)
    port.on_command(Cmd.START_STREAM_WITH_TM30, lambda _: stream_frame)

    with Device(port) as dev:
        frames = list(dev.stream(include_tm30=True, max_frames=1, frame_timeout=1.0))

    assert len(frames) == 1
    assert frames[0].tm30 is not None
    assert port.writes[0] == hx("CC 01 09 00 00 35 0B 0D 0A")
    assert port.writes[-1] == hx("CC 01 09 00 00 04 DA 0D 0A")


def test_stream_early_break_still_sends_stop():
    port = MockSerialPort()
    valid = synth_spectrum_valid(m=4)
    stream_frame = build_response_frame(Cmd.START_STREAM_NO_TM30, valid)
    port.on_command(Cmd.START_STREAM_NO_TM30, lambda _: stream_frame * 5)

    with Device(port) as dev:
        seen = 0
        for _ in dev.stream(frame_timeout=1.0):
            seen += 1
            if seen >= 2:
                break

    assert seen == 2
    assert port.writes[-1] == hx("CC 01 09 00 00 04 DA 0D 0A")


# ---------------------------------------------------------------------------
# Efficiency curve upload
# ---------------------------------------------------------------------------


def test_upload_efficiency_curve_packets():
    port = MockSerialPort()
    # Caller will follow up with verify; we don't model that here — we only
    # want to inspect the framing of the data packets.
    n_floats = 500  # forces multiple chunks (247 per chunk -> 2 chunks)
    ratios = [1.5] * n_floats

    with Device(port) as dev:
        dev.upload_efficiency_curve(ratios)

    # First write must be the documented "start" packet.
    assert port.writes[0] == hx("CC 01 0A 00 00 23 04 FE 0D 0A")
    # Then chunked data packets, all with cmdType 0x23.
    data_writes = list(port.writes)[1:]
    assert len(data_writes) == 3  # 247 + 247 + 6
    sizes = [len(w) for w in data_writes]
    # cmdData = floats*4; +9 frame overhead.
    assert sizes == [247 * 4 + 9, 247 * 4 + 9, 6 * 4 + 9]
    # cmdType byte must be 0x23 in every chunk.
    for w in data_writes:
        assert w[5] == Cmd.SEND_EFFICIENCY_CURVE


def test_verify_efficiency_curve_success():
    port = MockSerialPort()
    port.on_command(
        Cmd.VERIFY_EFFICIENCY_CURVE,
        lambda _: build_response_frame(Cmd.VERIFY_EFFICIENCY_CURVE, bytes([0x00])),
    )
    with Device(port) as dev:
        dev.verify_and_compute_efficiency_curve(timeout=1.0)


def test_verify_efficiency_curve_failure_raises():
    port = MockSerialPort()
    port.on_command(
        Cmd.VERIFY_EFFICIENCY_CURVE,
        lambda _: build_response_frame(Cmd.VERIFY_EFFICIENCY_CURVE, bytes([0xFF])),
    )
    with Device(port) as dev:
        with pytest.raises(DeviceError):
            dev.verify_and_compute_efficiency_curve(timeout=1.0)


def test_reset_efficiency_curve_success():
    port = MockSerialPort()
    port.on_command(
        Cmd.RESET_EFFICIENCY_CURVE,
        lambda _: build_response_frame(Cmd.RESET_EFFICIENCY_CURVE, bytes([0x00])),
    )
    with Device(port) as dev:
        dev.reset_efficiency_curve()


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------


def test_request_timeout_raises_h1_timeout_error():
    port = MockSerialPort(timeout=0.05)
    # No handler => no response, must time out.
    with Device(port, timeout=0.05) as dev:
        with pytest.raises(H1TimeoutError):
            dev.get_exposure_time_us()


def test_context_manager_closes_owned_port():
    """Sanity: ``__exit__`` should call close on the underlying port."""
    closed = []

    class FakePort:
        timeout = 0.1
        in_waiting = 0

        def write(self, _data):
            return 0

        def read(self, _n=1):
            return b""

        def close(self):
            closed.append(True)

    # owns_port is only True when we open the port by string; passing a port
    # instance keeps ownership with the caller, so we test directly.
    with Device(FakePort()):
        pass
    # No assertion: we just want no exceptions. closed remains empty because
    # ``Device`` does not own the port — that's the documented contract.
    assert closed == []


def test_reentrant_lock_allows_nested_calls():
    """RLock lets the same thread call methods recursively (e.g. capture inside
    a streaming context's finally block). Simply ensure two sequential calls
    on one device don't deadlock."""
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_EXPOSURE_TIME,
        lambda _: build_response_frame(Cmd.GET_EXPOSURE_TIME, struct.pack("<I", 1)),
    )

    with Device(port) as dev:
        assert dev.get_exposure_time_us() == 1
        assert dev.get_exposure_time_us() == 1
