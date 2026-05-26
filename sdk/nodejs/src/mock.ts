/**
 * In-memory mock of the `serialport` API.
 *
 * The mock intentionally implements just the surface used by `Device`:
 *  - `on('data', cb)` / `off('data', cb)` / `removeListener('data', cb)`
 *  - `on('close', cb)` / `on('error', cb)`
 *  - `write(chunk, cb?)`
 *  - `close(cb?)`
 *  - `isOpen` getter
 *
 * Tests register handlers via {@link MockSerialPort.onWrite} (called every time
 * the SDK writes a frame to the port) and feed the SDK by calling
 * {@link MockSerialPort.emitData} with the bytes the device would have replied
 * with. The most common pattern is a request/response map:
 *
 * ```ts
 * const port = new MockSerialPort();
 * port.respondTo(buildGetDeviceInfo(), Buffer.from('CC81...', 'hex'));
 * const device = new Device(port as unknown as SerialPort);
 * ```
 */

import { EventEmitter } from 'node:events';

/** Callback invoked with each chunk the SDK writes to the port. */
export type WriteListener = (chunk: Buffer) => void;

export interface MockSerialPortOptions {
  /** If true, log writes and reads to stderr. */
  debug?: boolean;
}

export class MockSerialPort extends EventEmitter {
  /** Mirrors the real `SerialPort#isOpen`. */
  isOpen = true;

  /**
   * Map from exact request bytes (as hex string) to a response builder. The
   * builder may be either a Buffer (returned synchronously) or a function that
   * returns a Buffer (allowing dynamic / stateful responses).
   */
  private readonly responses = new Map<string, Buffer | ((req: Buffer) => Buffer | Buffer[] | undefined)>();

  private readonly writeListeners = new Set<WriteListener>();
  private readonly debug: boolean;

  constructor(opts: MockSerialPortOptions = {}) {
    super();
    this.debug = opts.debug ?? false;
  }

  /**
   * Register a canned reply for a specific request. Subsequent writes whose
   * bytes equal `request` will trigger `response` to be emitted as data on the
   * next tick.
   */
  respondTo(
    request: Buffer,
    response: Buffer | Buffer[] | ((req: Buffer) => Buffer | Buffer[] | undefined),
  ): void {
    const key = request.toString('hex');
    if (typeof response === 'function') {
      this.responses.set(key, response);
    } else if (Array.isArray(response)) {
      const frames = response;
      this.responses.set(key, () => frames);
    } else {
      this.responses.set(key, response);
    }
  }

  /** Register a write listener used to drive custom server behaviour. */
  onWrite(listener: WriteListener): void {
    this.writeListeners.add(listener);
  }

  /** Remove a previously-registered write listener. */
  offWrite(listener: WriteListener): void {
    this.writeListeners.delete(listener);
  }

  /**
   * Feed bytes to the SDK as if they had arrived from the device. The bytes
   * are delivered synchronously via `this.emit('data', chunk)`.
   */
  emitData(chunk: Buffer | Uint8Array): void {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    if (this.debug) {
      // eslint-disable-next-line no-console
      console.error('[mock] -> SDK:', buf.toString('hex'));
    }
    this.emit('data', buf);
  }

  // --- serialport API ------------------------------------------------------

  write(chunk: Buffer | Uint8Array | string, cb?: (err?: Error | null) => void): boolean {
    const buf = Buffer.isBuffer(chunk)
      ? chunk
      : typeof chunk === 'string'
        ? Buffer.from(chunk, 'utf8')
        : Buffer.from(chunk);
    if (this.debug) {
      // eslint-disable-next-line no-console
      console.error('[mock] <- SDK:', buf.toString('hex'));
    }
    for (const listener of this.writeListeners) {
      try {
        listener(buf);
      } catch (err) {
        if (cb) cb(err as Error);
        return false;
      }
    }
    const handler = this.responses.get(buf.toString('hex'));
    if (handler !== undefined) {
      const reply = typeof handler === 'function' ? handler(buf) : handler;
      if (reply !== undefined) {
        const frames = Array.isArray(reply) ? reply : [reply];
        // Defer to next tick so the caller has a chance to await its promise.
        queueMicrotask(() => {
          for (const frame of frames) {
            this.emit('data', frame);
          }
        });
      }
    }
    if (cb) cb(null);
    return true;
  }

  close(cb?: (err?: Error | null) => void): void {
    if (!this.isOpen) {
      if (cb) cb(null);
      return;
    }
    this.isOpen = false;
    queueMicrotask(() => {
      this.emit('close');
      if (cb) cb(null);
    });
  }

  /** No-op stub mirroring serialport's `open()` for symmetry. */
  open(cb?: (err?: Error | null) => void): void {
    this.isOpen = true;
    if (cb) cb(null);
  }
}
