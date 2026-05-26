#!/usr/bin/env node
/**
 * `h1` CLI — thin wrapper around the Device class. See spec §10 for the
 * documented sub-command list.
 *
 * Usage:
 *   h1 info                              # device serial number + wavelength range
 *   h1 capture [--tm30] [--port PATH]    # single capture
 *   h1 stream [--count N] [--tm30] [--csv FILE] [--port PATH]
 *   h1 set-exposure <us>
 *   h1 get-exposure
 *   h1 set-mode <auto|manual>
 *   h1 get-mode
 *   h1 reset-curve
 */

import { Command } from 'commander';
import { writeFileSync } from 'node:fs';

import { Device } from './device.js';
import { CieMode, ExposureMode } from './types.js';

interface GlobalOptions {
  port: string;
  baud: string;
}

function resolveOptions(cmd: Command): GlobalOptions {
  const opts = cmd.optsWithGlobals<GlobalOptions>();
  if (!opts.port) {
    throw new Error('--port is required (or set $H1_PORT)');
  }
  return opts;
}

async function withDevice<T>(opts: GlobalOptions, fn: (d: Device) => Promise<T>): Promise<T> {
  const device = new Device(opts.port, { baudRate: Number(opts.baud) });
  try {
    return await fn(device);
  } finally {
    await device.close();
  }
}

function parseExposureMode(v: string): ExposureMode {
  switch (v.toLowerCase()) {
    case 'manual':
      return ExposureMode.Manual;
    case 'auto':
      return ExposureMode.Auto;
    default:
      throw new Error(`unknown exposure mode "${v}" (expected "auto" or "manual")`);
  }
}

function formatExposureMode(m: ExposureMode): string {
  return m === ExposureMode.Auto ? 'auto' : 'manual';
}

function formatCieMode(m: CieMode): string {
  switch (m) {
    case CieMode.Cie1931_2:
      return 'CIE1931 2°';
    case CieMode.Cie1964_10:
      return 'CIE1964 10°';
    case CieMode.Cie2015_2:
      return 'CIE2015 2°';
    case CieMode.Cie2015_10:
      return 'CIE2015 10°';
    default:
      return `unknown (${m})`;
  }
}

export function buildProgram(): Command {
  const program = new Command();
  program
    .name('h1')
    .description('CLI for the H1 spectrometer SDK')
    .option('-p, --port <path>', 'serial port path', process.env.H1_PORT)
    .option('-b, --baud <rate>', 'baud rate', '115200');

  program
    .command('info')
    .description('print device serial number and wavelength range')
    .action(async (_args, cmd: Command) => {
      const opts = resolveOptions(cmd);
      await withDevice(opts, async (d) => {
        const info = await d.getDeviceInfo();
        const range = await d.getWavelengthRange();
        const mode = await d.getExposureMode();
        const us = await d.getExposureTimeUs();
        const cie = await d.getCieMode();
        process.stdout.write(
          `serialNumber : ${info.serialNumber}\n` +
            `wavelength   : ${range.start} - ${range.end} nm\n` +
            `exposureMode : ${formatExposureMode(mode)}\n` +
            `exposureTime : ${us} us\n` +
            `cieMode      : ${formatCieMode(cie)}\n`,
        );
      });
    });

  program
    .command('capture')
    .description('capture a single spectrum frame')
    .option('--tm30', 'include TM-30 metrics', false)
    .action(async (_args, cmd: Command) => {
      const opts = resolveOptions(cmd);
      const tm30 = Boolean(cmd.opts<{ tm30: boolean }>().tm30);
      await withDevice(opts, async (d) => {
        const frame = await d.captureSingle(tm30);
        const p = frame.photometric;
        process.stdout.write(
          `exposureStatus : ${frame.exposureStatus}\n` +
            `exposureTime   : ${frame.exposureTimeUs} us\n` +
            `CCT            : ${p.CCT.toFixed(1)} K\n` +
            `Ra             : ${p.Ra.toFixed(2)}\n` +
            `lux            : ${p.lux.toFixed(2)}\n` +
            `samples        : ${frame.rawSpectrum.length}\n`,
        );
      });
    });

  program
    .command('stream')
    .description('continuously capture frames')
    .option('-n, --count <N>', 'stop after N frames', '10')
    .option('--tm30', 'include TM-30 metrics', false)
    .option('--csv <file>', 'append a CSV row per frame to FILE')
    .action(async (_args, cmd: Command) => {
      const opts = resolveOptions(cmd);
      const local = cmd.opts<{ count: string; tm30: boolean; csv?: string }>();
      const count = Number(local.count);
      const tm30 = Boolean(local.tm30);
      const csvPath = local.csv;
      await withDevice(opts, async (d) => {
        let received = 0;
        const rows: string[] = [];
        const done = new Promise<void>((resolve, reject) => {
          d.on('frame', (frame) => {
            received++;
            const p = frame.photometric;
            process.stdout.write(
              `[${received}/${count}] cct=${p.CCT.toFixed(0)}K  lux=${p.lux.toFixed(1)}  status=${frame.exposureStatus}\n`,
            );
            if (csvPath) {
              rows.push(
                [received, frame.exposureTimeUs, p.CCT, p.Ra, p.lux, p.Ee].join(','),
              );
            }
            if (received >= count) {
              d.stopStreaming().then(resolve, reject);
            }
          });
          d.on('error', reject);
        });
        await d.startStreaming(tm30);
        await done;
        if (csvPath) {
          writeFileSync(csvPath, ['idx,exposure_us,cct,ra,lux,ee', ...rows].join('\n'));
        }
      });
    });

  program
    .command('set-exposure <us>')
    .description('set exposure time in microseconds (also switches to manual mode)')
    .action(async (us: string, _opts, cmd: Command) => {
      const opts = resolveOptions(cmd);
      await withDevice(opts, async (d) => {
        await d.setExposureMode(ExposureMode.Manual);
        await d.setExposureTimeUs(Number(us));
        process.stdout.write(`exposure set to ${us} us\n`);
      });
    });

  program
    .command('get-exposure')
    .description('print the current exposure time in microseconds')
    .action(async (_args, cmd: Command) => {
      const opts = resolveOptions(cmd);
      await withDevice(opts, async (d) => {
        const us = await d.getExposureTimeUs();
        process.stdout.write(`${us}\n`);
      });
    });

  program
    .command('set-mode <auto|manual>')
    .description('set the exposure mode')
    .action(async (value: string, _opts, cmd: Command) => {
      const opts = resolveOptions(cmd);
      const mode = parseExposureMode(value);
      await withDevice(opts, async (d) => {
        await d.setExposureMode(mode);
        process.stdout.write(`exposure mode set to ${formatExposureMode(mode)}\n`);
      });
    });

  program
    .command('get-mode')
    .description('print the current exposure mode')
    .action(async (_args, cmd: Command) => {
      const opts = resolveOptions(cmd);
      await withDevice(opts, async (d) => {
        const m = await d.getExposureMode();
        process.stdout.write(`${formatExposureMode(m)}\n`);
      });
    });

  program
    .command('reset-curve')
    .description('reset the device efficiency curve to factory defaults')
    .action(async (_args, cmd: Command) => {
      const opts = resolveOptions(cmd);
      await withDevice(opts, async (d) => {
        await d.resetEfficiencyCurve();
        process.stdout.write('efficiency curve reset\n');
      });
    });

  return program;
}

// Detect "this file is the program entry point" in a way that works for both
// ESM and CJS builds. In ESM we compare import.meta.url to argv[1]; in CJS
// (when import.meta is unavailable) we fall through and the consumer is
// expected to call buildProgram() themselves.
const isMainModule = ((): boolean => {
  try {
    return import.meta.url === `file://${process.argv[1]}`;
  } catch {
    return false;
  }
})();

if (isMainModule) {
  buildProgram()
    .parseAsync(process.argv)
    .catch((err) => {
      process.stderr.write(`${(err as Error).stack ?? err}\n`);
      process.exit(1);
    });
}
