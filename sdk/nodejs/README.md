# @h1/sdk

Node.js / TypeScript SDK for the **H1 spectrometer** over USB serial.

- Covers all 20 commands documented in [`docs/PROTOCOL.md`](../../docs/PROTOCOL.md).
- Pure-TypeScript protocol layer (no native bindings beyond `serialport`).
- Promise-based API, EventEmitter for streaming captures.
- Includes a `MockSerialPort` so you can write tests without hardware.
- Ships CJS + ESM + `.d.ts`.

## Install

```bash
npm install @h1/sdk
```

Requires Node.js 18 or newer. `serialport@^12` is a peer/runtime dependency and
will be installed automatically.

## Quick start

```ts
import { Device, ExposureMode } from '@h1/sdk';

const dev = new Device('/dev/cu.usbserial-XXX');

const info = await dev.getDeviceInfo();
console.log('Serial:', info.serialNumber);

await dev.setExposureMode(ExposureMode.Auto);
const frame = await dev.captureSingle();
console.log('CCT:', frame.photometric.CCT);
console.log('Samples:', frame.rawSpectrum.length);

await dev.close();
```

Streaming capture:

```ts
const dev = new Device('/dev/cu.usbserial-XXX');
dev.on('frame', (f) => console.log(f.exposureTimeUs, f.photometric.lux));
dev.on('error', (e) => console.error(e));
await dev.startStreaming();
// ... later ...
await dev.stopStreaming();
await dev.close();
```

## API at a glance

| Method | Notes |
|---|---|
| `getDeviceInfo()` | 24-char serial number |
| `getWavelengthRange()` | `{ start, end }` in nm |
| `getExposureMode()` / `setExposureMode(mode)` | `ExposureMode.Manual` / `Auto` |
| `getExposureTimeUs()` / `setExposureTimeUs(us)` | microseconds |
| `getMaxExposureTimeUs()` / `setMaxExposureTimeUs(us)` | microseconds |
| `getCieMode()` / `setCieMode(mode)` | `CieMode.Cie1931_2` … `Cie2015_10` |
| `setWorkingMode(mode)` | `WorkingMode.Streaming` / `Trigger` |
| `enterSleep()` / `exitSleep()` / `enterExitSleep()` | toggle sleep |
| `captureSingle(includeTm30?)` | one `SpectrumFrame` |
| `startStreaming(includeTm30?)` / `stopStreaming()` | events: `'frame'`, `'error'`, `'close'` |
| `uploadEfficiencyCurve(ratios)` | chunked upload + verify |
| `verifyAndComputeEfficiencyCurve()` | trigger flash write |
| `resetEfficiencyCurve()` | factory reset |
| `close()` | tear down listeners + close owned port |

Every Device method returns a `Promise`. Errors are subclasses of `H1Error`:

- `ProtocolError` — malformed frame (bad header, footer, length, checksum, or
  unexpected dataType).
- `TimeoutError` — serial read did not complete in time.
- `DeviceError` — device returned status `0x15` (invalid command) or `0xFF`
  (unsupported / out of range). `err.code` and `err.cmdType` are exposed.

### Data layout

`SpectrumFrame.photometric`, `.blueHazard`, `.nir`, `.plant`, and (optional)
`.tm30` mirror the byte layout in `docs/PROTOCOL.md §5`. Field order and names
match the C++ and Python SDKs.

`spectrumCoefficient` is the power-of-ten divisor; the SDK pre-computes a
convenience `actualSpectrum: Float32Array` such that
`actualSpectrum[i] === rawSpectrum[i] / 10**spectrumCoefficient`.

## CLI

The package installs a `h1` binary (uses `commander`):

```bash
h1 info --port /dev/cu.usbserial-XXX
h1 capture --tm30 --port /dev/cu.usbserial-XXX
h1 stream --count 20 --csv frames.csv --port /dev/cu.usbserial-XXX
h1 set-exposure 50000 --port /dev/cu.usbserial-XXX
h1 get-exposure --port /dev/cu.usbserial-XXX
h1 set-mode auto --port /dev/cu.usbserial-XXX
h1 get-mode --port /dev/cu.usbserial-XXX
h1 reset-curve --port /dev/cu.usbserial-XXX
```

`--port` defaults to `$H1_PORT`.

## Examples

`examples/01_device_info.ts` … `examples/05_efficiency_curve.ts` — run with
`H1_PORT=... npx tsx examples/01_device_info.ts`.

## Testing without hardware

```ts
import { Device } from '@h1/sdk';
import { MockSerialPort } from '@h1/sdk/mock';
import { buildGetDeviceInfo } from '@h1/sdk';

const port = new MockSerialPort();
port.respondTo(
  buildGetDeviceInfo(),
  Buffer.from('CC8121000008483131423656313035333443465044...B50D0A', 'hex'),
);
const dev = new Device(port as any);
console.log((await dev.getDeviceInfo()).serialNumber);
```

The mock supports per-request canned replies, write listeners for stateful
servers, and synchronous `emitData()` for hand-fed test scenarios.

## Build / test

```bash
npm install
npm test        # vitest unit tests (no hardware required)
npm run build   # tsup → dist/{index,mock,cli}.{js,cjs,d.ts}
```

## License

MIT
