/**
 * Single-process device manager.
 *
 * Holds at most one live `Device` (mock or real) and exposes lazy
 * accessors used by Route Handlers. Stored on `globalThis` so the singleton
 * survives Next dev-mode hot reloads.
 *
 * Connection model:
 *  - The webui starts disconnected.
 *  - First `connect({mode:'mock'})` (or `connect({mode:'serial', port})`) opens.
 *  - `H1_PORT=/dev/...` enables eager serial connect on first access.
 *  - Without `H1_PORT`, the first access probes common USB serial paths and
 *    keeps the first port that answers H1 device-info and wavelength commands.
 *  - `H1_MOCK=1` explicitly enables eager mock connect; mock is never the
 *    fallback for missing hardware config.
 */

import { readdir } from 'node:fs/promises';

import { Device } from '@h1/sdk';
import { MockSerialPort } from '@h1/sdk/mock';
import { SerialPort } from 'serialport';

import { logCaptureSdkIo } from './log-capture';
import { attachMockHandlers, type MockPortLike } from './mock-data';

export type DeviceMode = 'mock' | 'serial';

export interface ConnectionStatus {
  connected: boolean;
  mode: DeviceMode | null;
  /** Serial path when mode==='serial'; literal "mock" otherwise. */
  port: string | null;
  /** ISO timestamp the connection was opened. */
  openedAt: string | null;
}

interface State {
  device: Device | null;
  serialPort: SerialPort | null;
  mockPort: MockSerialPort | null;
  mockDispose: (() => void) | null;
  status: ConnectionStatus;
  autoConnectPromise: Promise<void> | null;
  lastAutoDiscoverAt: number | null;
}

declare global {
  var __h1_state__: State | undefined;
}

function getState(): State {
  if (!globalThis.__h1_state__) {
    globalThis.__h1_state__ = {
      device: null,
      serialPort: null,
      mockPort: null,
      mockDispose: null,
      status: { connected: false, mode: null, port: null, openedAt: null },
      autoConnectPromise: null,
      lastAutoDiscoverAt: null,
    };
  }
  return globalThis.__h1_state__;
}

const AUTO_DISCOVER_RETRY_MS = 10_000;
const AUTO_PROBE_TIMEOUT_MS = 1_500;

const DARWIN_CU_PATTERNS = [
  /^cu\.usbserial/i,
  /^cu\.usbmodem/i,
  /^cu\.wchusbserial/i,
  /^cu\.SLAB_USBtoUART/i,
];
const DARWIN_TTY_PATTERNS = [
  /^tty\.usbserial/i,
  /^tty\.usbmodem/i,
  /^tty\.wchusbserial/i,
  /^tty\.SLAB_USBtoUART/i,
];
const LINUX_SERIAL_PATTERNS = [/^ttyUSB\d+$/i, /^ttyACM\d+$/i];

interface OpenSerialResult {
  device: Device;
  port: string;
  serialPort: SerialPort;
}

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

export function getStatus(): ConnectionStatus {
  return { ...getState().status };
}

/** Throws if not connected — Route Handlers can catch and 409. */
export function requireDevice(): Device {
  const s = getState();
  if (!s.device) throw new NotConnectedError();
  return s.device;
}

export class NotConnectedError extends Error {
  constructor() {
    super('设备未连接');
    this.name = 'NotConnectedError';
  }
}

export interface ConnectOptions {
  mode: DeviceMode;
  port?: string;
}

export async function connect(opts: ConnectOptions): Promise<ConnectionStatus> {
  const s = getState();
  const explicitPort = opts.port?.trim();
  if (s.device) {
    if (opts.mode === s.status.mode) {
      if (opts.mode === 'mock') return getStatus();
      if (!explicitPort || explicitPort === s.status.port) return getStatus();
    }
    await disconnect();
  }
  if (opts.mode === 'mock') {
    const port = new MockSerialPort();
    const mockDispose = attachMockHandlers(port as unknown as MockPortLike).dispose;
    const device = new Device(port as unknown as ConstructorParameters<typeof Device>[0]);
    logCaptureSdkIo(port, 'mock');
    s.device = device;
    s.serialPort = null;
    s.mockPort = port;
    s.mockDispose = mockDispose;
    s.status = {
      connected: true,
      mode: 'mock',
      port: 'mock',
      openedAt: new Date().toISOString(),
    };
    return getStatus();
  }

  const opened = explicitPort
    ? await openVerifiedSerialDevice(explicitPort)
    : await openFirstAvailableSerialDevice();
  if (!opened) {
    throw new Error('未找到可自动连接的 H1 串口');
  }

  s.device = opened.device;
  s.serialPort = opened.serialPort;
  s.mockPort = null;
  s.mockDispose = null;
  s.status = {
    connected: true,
    mode: 'serial',
    port: opened.port,
    openedAt: new Date().toISOString(),
  };
  return getStatus();
}

export async function disconnect(): Promise<ConnectionStatus> {
  const s = getState();
  if (s.device) {
    try {
      await s.device.close();
    } catch {
      // Ignore close errors; we are tearing down regardless.
    }
  }
  if (s.serialPort) {
    await closeSerialPortQuietly(s.serialPort);
  }
  s.mockDispose?.();
  s.device = null;
  s.serialPort = null;
  s.mockPort = null;
  s.mockDispose = null;
  s.status = { connected: false, mode: null, port: null, openedAt: null };
  return getStatus();
}

/** Lazy auto-connect for explicit env configuration. Idempotent. */
export async function ensureAutoConnect(): Promise<void> {
  const s = getState();
  if (s.device) return;
  if (s.autoConnectPromise) {
    await s.autoConnectPromise;
    return;
  }

  const promise = runAutoConnect();
  s.autoConnectPromise = promise;
  try {
    await promise;
  } finally {
    if (getState().autoConnectPromise === promise) {
      getState().autoConnectPromise = null;
    }
  }
}

async function runAutoConnect(): Promise<void> {
  const s = getState();
  if (s.device) return;

  if (process.env.H1_MOCK === '1') {
    await connect({ mode: 'mock' });
    return;
  }

  const h1Port = process.env.H1_PORT?.trim();
  if (h1Port) {
    await connect({ mode: 'serial', port: h1Port });
    return;
  }

  if (process.env.H1_AUTO_CONNECT === '0') return;

  const now = Date.now();
  if (s.lastAutoDiscoverAt && now - s.lastAutoDiscoverAt < AUTO_DISCOVER_RETRY_MS) {
    return;
  }
  s.lastAutoDiscoverAt = now;

  const opened = await openFirstAvailableSerialDevice();
  if (!opened) return;

  const current = getState();
  if (current.device) {
    await closeOpenedSerialQuietly(opened);
    return;
  }
  current.device = opened.device;
  current.serialPort = opened.serialPort;
  current.mockPort = null;
  current.mockDispose = null;
  current.status = {
    connected: true,
    mode: 'serial',
    port: opened.port,
    openedAt: new Date().toISOString(),
  };
}

async function openFirstAvailableSerialDevice(): Promise<OpenSerialResult | null> {
  const candidates = await discoverSerialCandidates();
  for (let attempt = 0; attempt < 2; attempt += 1) {
    for (const port of candidates) {
      try {
        return await openVerifiedSerialDevice(port);
      } catch {
        // Keep probing; non-H1 serial adapters should not make status polling fail.
      }
    }
    if (candidates.length > 0 && attempt === 0) {
      await sleep(500);
    }
  }
  return null;
}

async function openVerifiedSerialDevice(port: string): Promise<OpenSerialResult> {
  const serialPort = await openNativeSerialPort(port);
  const device = new Device(serialPort, { defaultTimeoutMs: AUTO_PROBE_TIMEOUT_MS });
  attachSerialErrorLogger(device, port);
  try {
    await verifyH1Device(device);
    return { device, port, serialPort };
  } catch (err) {
    await closeOpenedSerialQuietly({ device, port, serialPort });
    throw err;
  }
}

async function openNativeSerialPort(port: string): Promise<SerialPort> {
  const serialPort = new SerialPort({
    path: port,
    baudRate: 115200,
    dataBits: 8,
    stopBits: 1,
    parity: 'none',
  });
  if (serialPort.isOpen) return serialPort;

  await new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      serialPort.off('open', onOpen);
      serialPort.off('error', onError);
    };
    const onOpen = () => {
      cleanup();
      resolve();
    };
    const onError = (err: Error) => {
      cleanup();
      reject(err);
    };
    serialPort.once('open', onOpen);
    serialPort.once('error', onError);
  });
  return serialPort;
}

async function verifyH1Device(device: Device): Promise<void> {
  await device.getDeviceInfo();
  await device.getWavelengthRange();
}

function attachSerialErrorLogger(device: Device, port: string): void {
  device.on('error', (err) => {
    console.error(`[h1] serial error on ${port}:`, err);
  });
}

async function closeDeviceQuietly(device: Device): Promise<void> {
  try {
    await device.close();
  } catch {
    // Best effort cleanup after a failed probe.
  }
}

async function closeOpenedSerialQuietly(opened: OpenSerialResult): Promise<void> {
  await closeDeviceQuietly(opened.device);
  await closeSerialPortQuietly(opened.serialPort);
}

async function closeSerialPortQuietly(serialPort: SerialPort): Promise<void> {
  if (!serialPort.isOpen) return;
  await new Promise<void>((resolve) => {
    serialPort.close(() => resolve());
  });
}

async function discoverSerialCandidates(): Promise<string[]> {
  if (process.platform === 'win32') {
    return Array.from({ length: 32 }, (_, i) => `COM${i + 1}`);
  }

  const candidates: string[] = [];
  if (process.platform === 'darwin') {
    candidates.push(...(await listDevEntries(DARWIN_CU_PATTERNS)));
    candidates.push(...(await listDevEntries(DARWIN_TTY_PATTERNS)));
  }
  candidates.push(...(await listLinuxSerialByIdEntries()));
  candidates.push(...(await listDevEntries(LINUX_SERIAL_PATTERNS)));
  return unique(candidates);
}

async function listDevEntries(patterns: RegExp[]): Promise<string[]> {
  try {
    const names = await readdir('/dev');
    return names
      .filter((name) => patterns.some((pattern) => pattern.test(name)))
      .sort()
      .map((name) => `/dev/${name}`);
  } catch {
    return [];
  }
}

async function listLinuxSerialByIdEntries(): Promise<string[]> {
  try {
    const names = await readdir('/dev/serial/by-id');
    return names.sort().map((name) => `/dev/serial/by-id/${name}`);
  } catch {
    return [];
  }
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values));
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
