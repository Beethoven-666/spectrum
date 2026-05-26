/**
 * Example 02 — single capture, print key photometric numbers.
 *
 * Usage: H1_PORT=/dev/cu.usbserial-XXX npx tsx examples/02_capture_once.ts
 */

import { Device, ExposureStatus } from '../src/index.js';

const port = process.env.H1_PORT;
if (!port) {
  process.stderr.write('Set H1_PORT to the serial port path before running.\n');
  process.exit(1);
}

function statusName(s: ExposureStatus): string {
  return { 0: 'normal', 1: 'over', 2: 'under' }[s] ?? `unknown(${s})`;
}

const device = new Device(port);
try {
  const frame = await device.captureSingle(false);
  process.stdout.write(`Exposure status : ${statusName(frame.exposureStatus)}\n`);
  process.stdout.write(`Exposure time   : ${frame.exposureTimeUs} us\n`);
  process.stdout.write(`CCT             : ${frame.photometric.CCT.toFixed(1)} K\n`);
  process.stdout.write(`Ra              : ${frame.photometric.Ra.toFixed(2)}\n`);
  process.stdout.write(`lux             : ${frame.photometric.lux.toFixed(2)}\n`);
  process.stdout.write(`PPFD            : ${frame.plant.PPFD.toFixed(2)} umol/(m²·s)\n`);
  process.stdout.write(`spectrum samples: ${frame.rawSpectrum.length}\n`);
} finally {
  await device.close();
}
