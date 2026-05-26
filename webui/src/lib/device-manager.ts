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
 *  - `H1_MOCK=1` env (set by `npm run dev` etc.) toggles eager mock connect on
 *    first access, so the dashboard works without clicking Connect.
 */

import { Device } from '@h1/sdk';
import { MockSerialPort } from '@h1/sdk/mock';

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
  mockPort: MockSerialPort | null;
  mockDispose: (() => void) | null;
  status: ConnectionStatus;
}

declare global {
  var __h1_state__: State | undefined;
}

function getState(): State {
  if (!globalThis.__h1_state__) {
    globalThis.__h1_state__ = {
      device: null,
      mockPort: null,
      mockDispose: null,
      status: { connected: false, mode: null, port: null, openedAt: null },
    };
  }
  return globalThis.__h1_state__;
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
  if (s.device) {
    await disconnect();
  }
  if (opts.mode === 'mock') {
    const port = new MockSerialPort();
    const mockDispose = attachMockHandlers(port as unknown as MockPortLike).dispose;
    const device = new Device(port as unknown as ConstructorParameters<typeof Device>[0]);
    logCaptureSdkIo(port, 'mock');
    s.device = device;
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
  // Serial path
  if (!opts.port) {
    throw new Error('serial mode requires a port path');
  }
  const device = new Device(opts.port);
  s.device = device;
  s.mockPort = null;
  s.mockDispose = null;
  s.status = {
    connected: true,
    mode: 'serial',
    port: opts.port,
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
  s.mockDispose?.();
  s.device = null;
  s.mockPort = null;
  s.mockDispose = null;
  s.status = { connected: false, mode: null, port: null, openedAt: null };
  return getStatus();
}

/**
 * Lazy auto-connect for first request when `H1_MOCK=1` is set. Idempotent.
 */
export async function ensureAutoConnect(): Promise<void> {
  const s = getState();
  if (s.device) return;
  if (process.env.H1_MOCK === '1' || !process.env.H1_PORT) {
    await connect({ mode: 'mock' });
    return;
  }
  await connect({ mode: 'serial', port: process.env.H1_PORT });
}
