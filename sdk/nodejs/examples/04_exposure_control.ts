/**
 * Example 04 — switch manual → set value → switch auto, compare results.
 *
 * Usage: H1_PORT=/dev/cu.usbserial-XXX npx tsx examples/04_exposure_control.ts
 */

import { Device, ExposureMode } from '../src/index.js';

const port = process.env.H1_PORT;
if (!port) {
  process.stderr.write('Set H1_PORT to the serial port path before running.\n');
  process.exit(1);
}

const device = new Device(port);
try {
  await device.setExposureMode(ExposureMode.Manual);
  await device.setExposureTimeUs(10_000); // 10 ms
  const manualFrame = await device.captureSingle(false);
  process.stdout.write(
    `[manual 10ms] status=${manualFrame.exposureStatus} ` +
      `lux=${manualFrame.photometric.lux.toFixed(2)}\n`,
  );

  await device.setExposureMode(ExposureMode.Auto);
  const autoFrame = await device.captureSingle(false);
  process.stdout.write(
    `[auto]        actualExposure=${autoFrame.exposureTimeUs}us ` +
      `status=${autoFrame.exposureStatus} ` +
      `lux=${autoFrame.photometric.lux.toFixed(2)}\n`,
  );
} finally {
  await device.close();
}
