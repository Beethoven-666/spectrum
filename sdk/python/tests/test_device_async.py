"""AsyncDevice tests using pytest-asyncio."""

from __future__ import annotations

import struct

import pytest

from h1_sdk import (
    AsyncDevice,
    CieMode,
    DeviceError,
    ExposureMode,
    ExposureStatus,
    MockSerialPort,
)
from h1_sdk.protocol import Cmd, build_response_frame


def _synth_spectrum_valid(*, m: int = 4, include_tm30: bool = False) -> bytes:
    parts = [bytes([ExposureStatus.Normal]), struct.pack("<I", 42)]
    parts.append(struct.pack("<47f", *([0.0] * 47)))
    parts.append(struct.pack("<f", 0.0))
    parts.append(struct.pack("<3f", *([0.0] * 3)))
    parts.append(struct.pack("<16f", *([0.0] * 16)))
    if include_tm30:
        parts.append(struct.pack("<614f", *([0.0] * 614)))
    parts.append(struct.pack("<h", 0))
    parts.append(struct.pack(f"<{m}H", *range(m)))
    return b"".join(parts)


@pytest.mark.asyncio
async def test_async_get_device_info():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_DEVICE_INFO,
        lambda _: build_response_frame(Cmd.GET_DEVICE_INFO, b"H11B6V10534CFPD-100-0002"),
    )
    async with AsyncDevice(port) as dev:
        info = await dev.get_device_info()
    assert info.serial_number == "H11B6V10534CFPD-100-0002"


@pytest.mark.asyncio
async def test_async_get_wavelength_range():
    port = MockSerialPort()
    port.on_command(
        Cmd.GET_WAVELENGTH_RANGE,
        lambda _: build_response_frame(Cmd.GET_WAVELENGTH_RANGE, struct.pack("<HH", 340, 1050)),
    )
    async with AsyncDevice(port) as dev:
        wr = await dev.get_wavelength_range()
    assert wr.start == 340 and wr.end == 1050


@pytest.mark.asyncio
async def test_async_setter_success():
    port = MockSerialPort()
    port.on_command(
        Cmd.SET_EXPOSURE_MODE,
        lambda _: build_response_frame(Cmd.SET_EXPOSURE_MODE, bytes([0x00])),
    )
    async with AsyncDevice(port) as dev:
        await dev.set_exposure_mode(ExposureMode.Manual)


@pytest.mark.asyncio
async def test_async_setter_failure_raises_device_error():
    port = MockSerialPort()
    port.on_command(
        Cmd.SET_CIE_MODE,
        lambda _: build_response_frame(Cmd.SET_CIE_MODE, bytes([0x15])),
    )
    async with AsyncDevice(port) as dev:
        with pytest.raises(DeviceError):
            await dev.set_cie_mode(CieMode.Cie2015_2)


@pytest.mark.asyncio
async def test_async_capture_single():
    port = MockSerialPort()
    valid = _synth_spectrum_valid(m=4)
    port.on_command(
        Cmd.CAPTURE_SINGLE_NO_TM30,
        lambda _: build_response_frame(Cmd.CAPTURE_SINGLE_NO_TM30, valid),
    )
    async with AsyncDevice(port) as dev:
        frame = await dev.capture_single(timeout=1.0)
    assert frame.exposure_time_us == 42
    assert frame.raw_spectrum == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_async_stream_yields_frames_and_sends_stop():
    port = MockSerialPort()
    valid = _synth_spectrum_valid(m=4)
    stream_frame = build_response_frame(Cmd.START_STREAM_NO_TM30, valid)
    port.on_command(Cmd.START_STREAM_NO_TM30, lambda _: stream_frame * 4)

    async with AsyncDevice(port) as dev:
        frames = []
        async for f in dev.stream(max_frames=3, frame_timeout=1.0):
            frames.append(f)

    assert len(frames) == 3
    # Last write must be CMD 0x04 (stop).
    assert port.writes[-1][5] == Cmd.STOP_CAPTURE
