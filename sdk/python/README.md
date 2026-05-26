# h1-sdk

Python SDK for the H1 spectrometer. Implements the full 20-command serial
protocol documented in [`docs/PROTOCOL.md`](../../docs/PROTOCOL.md).

* Python 3.9+
* Sync (`Device`) and async (`AsyncDevice`) APIs
* Pure-Python protocol codec (no native deps)
* Pluggable transport — bring any `pyserial`-shaped port, including the
  bundled `MockSerialPort` for tests

## Install

From the SDK directory:

```bash
pip install -e .
# with development extras:
pip install -e ".[dev]"
```

This pulls in `pyserial>=3.5`. The optional `dev` extra adds `pytest`,
`pytest-asyncio`, and `pytest-cov`.

## Quick start

### One-shot capture

```python
from h1_sdk import Device, ExposureMode

with Device("/dev/tty.usbserial-XYZ") as dev:
    info = dev.get_device_info()
    print("connected to", info.serial_number)

    dev.set_exposure_mode(ExposureMode.Auto)
    frame = dev.capture_single()

    print(f"CCT = {frame.photometric.CCT:.0f} K")
    print(f"Ra  = {frame.photometric.Ra:.2f}")
    print(f"lux = {frame.photometric.lux:.2f}")
```

### Streaming

```python
with Device("/dev/tty.usbserial-XYZ") as dev:
    for i, frame in enumerate(dev.stream(max_frames=10)):
        print(i, frame.exposure_time_us, frame.photometric.CCT)
```

`dev.stream()` sends `0x33` (or `0x35` if `include_tm30=True`) to start the
stream and `0x04` to stop it, both automatically. Pass `max_frames=N` to
auto-stop after `N` frames, or break out of the loop.

### Async

```python
import asyncio
from h1_sdk import AsyncDevice

async def main():
    async with AsyncDevice("/dev/tty.usbserial-XYZ") as dev:
        info = await dev.get_device_info()
        async for frame in dev.stream(max_frames=5):
            print(frame.photometric.CCT)

asyncio.run(main())
```

### Testing without hardware

```python
from h1_sdk import Device, MockSerialPort
from h1_sdk.protocol import build_frame, Cmd

port = MockSerialPort()
port.on_command(
    Cmd.GET_DEVICE_INFO,
    lambda _data: build_frame(Cmd.GET_DEVICE_INFO, b"H11B6V10534CFPD-100-0002"),
)

with Device(port) as dev:
    assert dev.get_device_info().serial_number == "H11B6V10534CFPD-100-0002"
```

## CLI

`pip install`-ing the package puts a `h1` script on your `$PATH`:

```bash
h1 info     --port /dev/tty.usbserial-XYZ
h1 capture  --port /dev/tty.usbserial-XYZ --tm30
h1 stream   --port /dev/tty.usbserial-XYZ --count 50 --csv out.csv
h1 set-exposure 100000 --port /dev/tty.usbserial-XYZ
h1 get-exposure        --port /dev/tty.usbserial-XYZ
h1 set-mode manual     --port /dev/tty.usbserial-XYZ
h1 reset-curve         --port /dev/tty.usbserial-XYZ
```

## API at a glance

| Category | Method |
|----------|--------|
| Meta | `get_device_info`, `get_wavelength_range` |
| Exposure | `set/get_exposure_mode`, `set/get_exposure_time_us`, `set/get_max_exposure_time_us` |
| Modes | `set/get_cie_mode`, `set_working_mode` |
| Power | `enter_sleep`, `exit_sleep` |
| Capture | `capture_single(include_tm30=False)`, `stream(include_tm30=False, max_frames=None)` |
| Calibration | `upload_efficiency_curve(ratios)`, `verify_and_compute_efficiency_curve()`, `reset_efficiency_curve()` |

All methods are mirrored on `AsyncDevice` with `await`-able semantics.

### Exceptions

* `H1Error` — base class
* `ProtocolError` — malformed frame (header, footer, totalLen, checksum, or dataType mismatch)
* `H1TimeoutError` — serial read timed out
* `DeviceError` — device returned `0x15` (invalid command) or `0xFF`
  (unsupported / out-of-range). Has `.code` and `.cmd_type` attributes.

### Data types

`SpectrumFrame` has:

* `exposure_status: ExposureStatus`
* `exposure_time_us: int`
* `photometric: PhotometricParams` (47 fields, see `PROTOCOL.md` §5.1)
* `blue_hazard: BlueHazardParams` (`Eb`)
* `nir: NirParams` (`redEe`, `nirEeA`, `nirEeB`)
* `plant: PlantParams` (16 fields)
* `spectrum_coefficient: int` (signed)
* `raw_spectrum: list[int]`
* `tm30: Tm30Params | None`
* `actual_spectrum` property = `raw_spectrum[i] / 10**spectrum_coefficient`

## Examples

Five runnable examples live in `examples/`:

1. `01_device_info.py` — connect, print SN + wavelength range
2. `02_capture_once.py` — single-frame capture summary
3. `03_stream.py` — 10-frame streaming demo
4. `04_exposure_control.py` — manual ↔ auto exposure
5. `05_efficiency_curve.py` — upload a flat unity ratio curve

Run with `python examples/01_device_info.py /dev/tty.usbserial-XYZ`.

## Tests

```bash
pytest -v
```

Tests cover every command in `docs/PROTOCOL.md` §9 plus
end-to-end Device flows over `MockSerialPort`.
