/**
 * Example 05 — upload an all-1.0 efficiency curve (a demo / sanity check that
 * exercises the multi-packet upload protocol).
 *
 * Usage: H1_PORT=/dev/cu.usbserial-XXX npx tsx examples/05_efficiency_curve.ts
 *
 * WARNING: this writes to the device's flash. Run only against a unit you are
 * willing to reconfigure. Run `npx tsx examples/05_efficiency_curve.ts reset`
 * to restore the factory curve.
 */

import { Device } from '../src/index.js';

const port = process.env.H1_PORT;
if (!port) {
  process.stderr.write('Set H1_PORT to the serial port path before running.\n');
  process.exit(1);
}

const device = new Device(port);
try {
  if (process.argv[2] === 'reset') {
    await device.resetEfficiencyCurve();
    process.stdout.write('efficiency curve reset to factory defaults\n');
  } else {
    const range = await device.getWavelengthRange();
    const length = range.end - range.start + 1;
    const ratios = new Float32Array(length).fill(1.0);
    process.stdout.write(`Uploading ${length} ratios (all 1.0)...\n`);
    await device.uploadEfficiencyCurve(ratios);
    process.stdout.write('upload complete, device verified the new curve\n');
  }
} finally {
  await device.close();
}
