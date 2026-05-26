# H1 spectrometer C++ SDK

C++17 SDK for the H1 spectrometer. Implements all 20 commands described in
[`docs/PROTOCOL.md`](../../docs/PROTOCOL.md) over a 115200 bps serial link.
Zero runtime dependencies beyond the standard library and pthreads;
`doctest` (tests) and `CLI11` (cli) are pulled in via CMake `FetchContent`.

Supported platforms: macOS, Linux, Windows.

## Build

Requires CMake 3.16+ and a C++17 compiler.

```sh
cmake -S sdk/cpp -B sdk/cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build sdk/cpp/build -j
ctest --test-dir sdk/cpp/build --output-on-failure
```

The build produces a static library target `h1::sdk`, the `h1_cli` tool,
five examples under `build/`, and the `h1_sdk_tests` test executable.

To skip the examples/CLI:
```sh
cmake -S sdk/cpp -B sdk/cpp/build -DH1_SDK_BUILD_EXAMPLES=OFF
```

To use the library from another CMake project:

```cmake
add_subdirectory(path/to/spectrum/sdk/cpp)
target_link_libraries(myapp PRIVATE h1::sdk)
```

## Quick start

```cpp
#include "h1/Device.hpp"
#include <iostream>

int main() {
    h1::Device dev(h1::openSerialPort("/dev/tty.usbserial-XYZ"));
    auto info = dev.getDeviceInfo();
    auto wr   = dev.getWavelengthRange();
    std::cout << "SN: " << info.serialNumber
              << "  range: " << wr.start << "-" << wr.end << " nm\n";

    auto frame = dev.captureSingle();
    std::cout << "CCT = " << frame.photometric.CCT << " K, lux = "
              << frame.photometric.lux << "\n";
}
```

Streaming:

```cpp
dev.startStreaming([](h1::SpectrumFrame f) {
    std::cout << f.exposureTimeUs << " us, lux=" << f.photometric.lux << "\n";
});
std::this_thread::sleep_for(std::chrono::seconds(5));
dev.stopStreaming();
```

The callback fires on a background thread; synchronise as appropriate.

## API surface

All methods live on `h1::Device` (see [`include/h1/Device.hpp`](include/h1/Device.hpp)).

| Method | Command(s) |
|---|---|
| `getDeviceInfo()` | 0x08 |
| `getWavelengthRange()` | 0x0F |
| `setExposureMode` / `getExposureMode` | 0x0A / 0x0B |
| `setExposureTimeUs` / `getExposureTimeUs` | 0x0C / 0x0D |
| `setMaxExposureTimeUs` / `getMaxExposureTimeUs` | 0x13 / 0x14 |
| `setCieMode` / `getCieMode` | 0x36 / 0x37 |
| `setWorkingMode` | 0x41 |
| `enterSleep` / `exitSleep` | 0x40 |
| `stopCapture` | 0x04 |
| `captureSingle(includeTm30)` | 0x32 / 0x34 |
| `startStreaming(onFrame, includeTm30)` / `stopStreaming` | 0x33 / 0x35 + 0x04 |
| `uploadEfficiencyCurve(ratios)` | 0x23 (chunked) |
| `verifyAndComputeEfficiencyCurve()` | 0x27 |
| `resetEfficiencyCurve()` | 0x25 |

Data types are in [`include/h1/Types.hpp`](include/h1/Types.hpp). Field
order matches `PROTOCOL.md §5` exactly.

## Exceptions

All errors derive from `h1::H1Error`:

| Type | When |
|---|---|
| `h1::ProtocolError` | bad header/footer, wrong totalLen, checksum mismatch, dataType mismatch |
| `h1::TimeoutError`  | serial read did not return a complete frame in time |
| `h1::DeviceError`   | device replied with status `0x15` (invalid) or `0xFF` (unsupported/out of range). `code()` and `cmdType()` expose the details. |

## Examples

Built next to the library; each takes the port path as its first arg.

| Binary | What it does |
|---|---|
| `01_device_info` | print SN and wavelength range |
| `02_capture_once` | capture one frame, show CCT/Ra/lux + spectrum preview |
| `03_stream` | continuous capture (default 10 frames, then stop) |
| `04_exposure_control` | manual ↔ auto switch, set 50 ms exposure, capture |
| `05_efficiency_curve` | upload an identity ratio array, then verify+commit |

## CLI

```sh
export H1_PORT=/dev/tty.usbserial-XXXX
./build/h1_cli info
./build/h1_cli capture --tm30
./build/h1_cli stream --count 20 --csv frames.csv
./build/h1_cli set-exposure 50000
./build/h1_cli get-mode
./build/h1_cli reset-curve
```

`--port`/`-p` overrides `$H1_PORT`.

## Threading

Each `Device` owns its serial port and serialises commands internally.
Streaming runs on a dedicated worker thread; the user callback executes
on that thread. Do not call other `Device` methods from inside the
streaming callback (apart from `stopStreaming`).

## Testing without hardware

The tests use a `MockSerialPort` (see `tests/MockSerialPort.hpp`) that
records writes and lets the test queue scripted responses. Any custom
serial backend can be plugged in by implementing `h1::ISerialPort` and
passing it to the `Device` constructor.
