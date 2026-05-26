/**
 * Example 03 — continuously capture 10 frames, then auto-stop.
 *
 * Usage: H1_PORT=/dev/cu.usbserial-XXX npx tsx examples/03_stream.ts
 */

import { Device, type SpectrumFrame } from '../src/index.js';

const port = process.env.H1_PORT;
if (!port) {
  process.stderr.write('Set H1_PORT to the serial port path before running.\n');
  process.exit(1);
}

const TARGET = 10;
const device = new Device(port);

try {
  let received = 0;
  const done = new Promise<void>((resolve, reject) => {
    device.on('frame', (frame: SpectrumFrame) => {
      received++;
      process.stdout.write(
        `[${received}/${TARGET}] CCT=${frame.photometric.CCT.toFixed(0)}K  ` +
          `lux=${frame.photometric.lux.toFixed(1)}\n`,
      );
      if (received >= TARGET) {
        device.stopStreaming().then(resolve, reject);
      }
    });
    device.on('error', reject);
  });

  await device.startStreaming(false);
  await done;
} finally {
  await device.close();
}
