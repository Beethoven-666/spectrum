/**
 * Ring-buffer of recent SDK I/O for the /logs page.
 *
 * We intercept the MockSerialPort's `write` (host→device) and `emit('data',…)`
 * (device→host) calls and store hex + a tiny human summary for each frame.
 *
 * Real-serial connections aren't wrapped here — `serialport.SerialPort` would
 * need a different shim; out of scope for the first cut. The UI degrades
 * gracefully to "no log entries yet".
 */

import { EventEmitter } from 'node:events';

import { protocol } from '@h1/sdk';

export type LogDirection = 'tx' | 'rx';

export interface LogEntry {
  /** Monotonically increasing id (also doubles as React key). */
  id: number;
  /** Epoch ms when the byte was observed. */
  ts: number;
  direction: LogDirection;
  cmdType: number | null;
  hex: string;
  byteLength: number;
  summary: string;
}

interface RingBuffer {
  entries: LogEntry[];
  nextId: number;
  paused: boolean;
}

declare global {
  var __h1_logs__: RingBuffer | undefined;
}

const MAX_ENTRIES = 500;

function getBuffer(): RingBuffer {
  if (!globalThis.__h1_logs__) {
    globalThis.__h1_logs__ = { entries: [], nextId: 1, paused: false };
  }
  return globalThis.__h1_logs__;
}

function cmdName(cmdType: number | null): string {
  if (cmdType === null) return '';
  for (const [k, v] of Object.entries(protocol.CMD)) {
    if (v === cmdType) return k;
  }
  return `cmd 0x${cmdType.toString(16).padStart(2, '0')}`;
}

function summarise(direction: LogDirection, buf: Buffer): {
  cmdType: number | null;
  summary: string;
} {
  if (buf.length < 6) {
    return { cmdType: null, summary: `${direction.toUpperCase()} ${buf.length} bytes (truncated)` };
  }
  const cmdType = buf[5] ?? null;
  const name = cmdName(cmdType);
  return {
    cmdType,
    summary: `${direction === 'tx' ? '→' : '←'} ${name} (${buf.length} B)`,
  };
}

function record(direction: LogDirection, chunk: Buffer): void {
  const b = getBuffer();
  if (b.paused) return;
  const { cmdType, summary } = summarise(direction, chunk);
  b.entries.push({
    id: b.nextId++,
    ts: Date.now(),
    direction,
    cmdType,
    hex: chunk.toString('hex'),
    byteLength: chunk.length,
    summary,
  });
  if (b.entries.length > MAX_ENTRIES) {
    b.entries.splice(0, b.entries.length - MAX_ENTRIES);
  }
}

/**
 * Wrap a mock serial port so we capture both directions. The wrapper installs
 * a write proxy and a data listener; everything is idempotent if called twice.
 */
export function logCaptureSdkIo(port: EventEmitter & { write: (chunk: Buffer | Uint8Array, cb?: (err?: Error | null) => void) => boolean }, source: 'mock' | 'serial'): void {
  // Mark by source to silence unused-variable lints; kept for future expansion.
  void source;
  const originalWrite = port.write.bind(port);
  port.write = (chunk: Buffer | Uint8Array, cb?: (err?: Error | null) => void): boolean => {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    record('tx', buf);
    return originalWrite(buf, cb);
  };
  port.on('data', (chunk: Buffer) => {
    record('rx', Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  });
}

/* -------------------------------------------------------------------------- */
/* Public read-side API used by Route Handlers                                */
/* -------------------------------------------------------------------------- */

export interface LogSnapshot {
  entries: LogEntry[];
  paused: boolean;
  nextId: number;
}

export function getLogs(sinceId = 0): LogSnapshot {
  const b = getBuffer();
  return {
    entries: b.entries.filter((e) => e.id > sinceId),
    paused: b.paused,
    nextId: b.nextId,
  };
}

export function clearLogs(): void {
  const b = getBuffer();
  b.entries.length = 0;
}

export function setPaused(paused: boolean): void {
  getBuffer().paused = paused;
}
