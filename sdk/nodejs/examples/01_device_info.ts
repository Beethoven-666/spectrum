/**
 * Example 01 — connect to a device, print SN and wavelength range.
 *
 * Usage: H1_PORT=/dev/cu.usbserial-XXX npx tsx examples/01_device_info.ts
 */

import { Device } from '../src/index.js';

const port = process.env.H1_PORT;
if (!port) {
  process.stderr.write('Set H1_PORT to the serial port path before running.\n');
  process.exit(1);
}

const device = new Device(port);
try {
  const info = await device.getDeviceInfo();
  const range = await device.getWavelengthRange();
  process.stdout.write(`Serial number    : ${info.serialNumber}\n`);
  process.stdout.write(`Wavelength range : ${range.start} - ${range.end} nm\n`);
} finally {
  await device.close();
}
