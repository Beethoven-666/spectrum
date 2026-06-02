/**
 * High-level Device class.
 *
 * The Device owns a single serial port (real `serialport.SerialPort` instance
 * or a {@link MockSerialPort}) and exposes a Promise-based wrapper around every
 * command in PROTOCOL.md. Streaming captures are surfaced via the EventEmitter
 * interface (`'frame'`, `'error'`, `'close'`).
 *
 * A single internal mutex guarantees that no two commands are in flight on the
 * same port at the same time — required because the device cannot multiplex
 * responses on a shared cmdType.
 */

import { EventEmitter } from 'node:events';

import { ProtocolError, TimeoutError } from './errors.js';
import {
  buildCaptureSingleNoTm30,
  buildCaptureSingleWithTm30,
  buildEnterExitSleep,
  buildGetCieMode,
  buildGetDeviceInfo,
  buildGetExposureMode,
  buildGetExposureTime,
  buildGetMaxExposureTime,
  buildGetWavelengthRange,
  buildResetEfficiencyCurve,
  buildSendEfficiencyCurveChunk,
  buildSendEfficiencyCurveStart,
  buildSetCieMode,
  buildSetExposureMode,
  buildSetExposureTime,
  buildSetMaxExposureTime,
  buildSetWorkingMode,
  buildStartStreamNoTm30,
  buildStartStreamWithTm30,
  buildStopCapture,
  buildVerifyEfficiencyCurve,
  checkSetStatus,
  CMD,
  decodeCieMode,
  decodeDeviceInfo,
  decodeExposureMode,
  decodeExposureTimeUs,
  decodeSpectrumFrame,
  decodeWavelengthRange,
  FRAME_OVERHEAD,
  HEADER_RESP_0,
  HEADER_RESP_1,
  parseResponse,
  peekTotalLen,
} from './protocol.js';
import type {
  CieMode,
  DeviceInfo,
  DeviceOptions,
  ExposureMode,
  SpectrumFrame,
  WavelengthRange,
  WorkingMode,
} from './types.js';

// Forward declaration of the minimal serialport surface the Device requires.
// Using a structural type lets us accept the real serialport.SerialPort, our
// MockSerialPort and any other compatible duplex stream without depending on
// `serialport` at the type level for downstream consumers.
export interface SerialPortLike extends EventEmitter {
  isOpen?: boolean;
  write(chunk: Buffer | Uint8Array, cb?: (err?: Error | null) => void): boolean;
  close(cb?: (err?: Error | null) => void): void;
}

/** Internal: in-flight request descriptor. */
interface PendingRequest {
  expectedCmdType: number;
  resolve(frame: Buffer): void;
  reject(err: Error): void;
  /** Set by the schedule loop. */
  timer?: NodeJS.Timeout;
}

const DEFAULT_TIMEOUT_MS = 1000;
/** Maximum cmdData per efficiency-curve packet (247 floats = 988 bytes). */
const EFFICIENCY_CHUNK_FLOATS = 247;
/**
 * Sanity cap on a frame's totalLen (1 MiB). The largest real frame is a TM30
 * spectrum (~4 KiB), so anything above this is a bogus header detected inside
 * payload data. Mirrors the Python SDK's 1_000_000 cap (the C++ SDK uses
 * 64 KiB); a totalLen outside [FRAME_OVERHEAD, MAX_FRAME_LEN] triggers resync.
 */
const MAX_FRAME_LEN = 1024 * 1024;

export class Device extends EventEmitter {
  private readonly port: SerialPortLike;
  private readonly defaultTimeoutMs: number;
  /** Owns lifecycle of a `port` we opened ourselves (from a path string). */
  private readonly ownsPort: boolean;

  /** Single-slot mutex queue for command serialisation. */
  private inflight: PendingRequest | undefined;
  private waitQueue: Array<() => void> = [];

  /** Rolling buffer of data bytes received from the port. */
  private rxBuffer: Buffer = Buffer.alloc(0);

  /**
   * Streaming state:
   *  - `mode`        — null when not streaming, else 0x33 or 0x35.
   *  - `stopping`    — true between calling stopStreaming() and the device
   *                    being fully drained, suppresses 'frame' emission for
   *                    trailing buffered frames.
   */
  private streamingMode: number | null = null;
  private stopping = false;

  private closed = false;

  /**
   * Construct a Device.
   *
   * @param port    Either an already-open SerialPort-compatible object, or a
   *                path string ("/dev/cu.usbserial-XXX", "COM3", ...). When a
   *                path is supplied the Device opens a `serialport.SerialPort`
   *                with the configured baud rate and takes ownership of it.
   * @param options Optional defaults (baud rate, timeout).
   */
  constructor(port: SerialPortLike | string, options: DeviceOptions = {}) {
    super();
    this.defaultTimeoutMs = options.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS;
    if (typeof port === 'string') {
      // Lazy require to avoid pulling serialport into mock-only callers.
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { SerialPort } = require('serialport') as typeof import('serialport');
      this.port = new SerialPort({
        path: port,
        baudRate: options.baudRate ?? 115200,
        dataBits: 8,
        stopBits: 1,
        parity: 'none',
      }) as unknown as SerialPortLike;
      this.ownsPort = true;
    } else {
      this.port = port;
      this.ownsPort = false;
    }
    this.attachListeners();
  }

  private attachListeners(): void {
    this.port.on('data', this.onData);
    this.port.on('close', this.onClose);
    this.port.on('error', this.onError);
  }

  // -------------------------------------------------------------------------
  // Lifecycle / events
  // -------------------------------------------------------------------------

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    if (this.streamingMode !== null) {
      try {
        await this.stopStreaming();
      } catch {
        // ignore — we're closing anyway
      }
    }
    this.port.off('data', this.onData);
    this.port.off('close', this.onClose);
    this.port.off('error', this.onError);
    if (this.ownsPort && this.port.isOpen !== false) {
      await new Promise<void>((resolve) => {
        this.port.close(() => resolve());
      });
    }
  }

  // -------------------------------------------------------------------------
  // Commands (one method per CMD in PROTOCOL.md)
  // -------------------------------------------------------------------------

  async getDeviceInfo(): Promise<DeviceInfo> {
    const { validData } = await this.request(buildGetDeviceInfo(), CMD.GetDeviceInfo);
    return decodeDeviceInfo(validData);
  }

  async getWavelengthRange(): Promise<WavelengthRange> {
    const { validData } = await this.request(buildGetWavelengthRange(), CMD.GetWavelengthRange);
    return decodeWavelengthRange(validData);
  }

  async setExposureMode(mode: ExposureMode): Promise<void> {
    const { validData } = await this.request(buildSetExposureMode(mode), CMD.SetExposureMode);
    checkSetStatus(validData, CMD.SetExposureMode);
  }

  async getExposureMode(): Promise<ExposureMode> {
    const { validData } = await this.request(buildGetExposureMode(), CMD.GetExposureMode);
    return decodeExposureMode(validData);
  }

  async setExposureTimeUs(us: number): Promise<void> {
    const { validData } = await this.request(buildSetExposureTime(us), CMD.SetExposureTime);
    checkSetStatus(validData, CMD.SetExposureTime);
  }

  async getExposureTimeUs(): Promise<number> {
    const { validData } = await this.request(buildGetExposureTime(), CMD.GetExposureTime);
    return decodeExposureTimeUs(validData);
  }

  async setMaxExposureTimeUs(us: number): Promise<void> {
    const { validData } = await this.request(buildSetMaxExposureTime(us), CMD.SetMaxExposureTime);
    checkSetStatus(validData, CMD.SetMaxExposureTime);
  }

  async getMaxExposureTimeUs(): Promise<number> {
    const { validData } = await this.request(buildGetMaxExposureTime(), CMD.GetMaxExposureTime);
    return decodeExposureTimeUs(validData);
  }

  async setCieMode(mode: CieMode): Promise<void> {
    const { validData } = await this.request(buildSetCieMode(mode), CMD.SetCieMode);
    checkSetStatus(validData, CMD.SetCieMode);
  }

  async getCieMode(): Promise<CieMode> {
    const { validData } = await this.request(buildGetCieMode(), CMD.GetCieMode);
    return decodeCieMode(validData);
  }

  async setWorkingMode(mode: WorkingMode): Promise<void> {
    const { validData } = await this.request(buildSetWorkingMode(mode), CMD.SetWorkingMode);
    checkSetStatus(validData, CMD.SetWorkingMode);
  }

  /**
   * Send the sleep/wake toggle command. No response is expected; the function
   * resolves once the bytes are queued.
   */
  async enterExitSleep(): Promise<void> {
    await this.writeBytes(buildEnterExitSleep());
  }

  /** Alias of {@link enterExitSleep}. */
  async enterSleep(): Promise<void> {
    return this.enterExitSleep();
  }

  /** Alias of {@link enterExitSleep}. */
  async exitSleep(): Promise<void> {
    return this.enterExitSleep();
  }

  /**
   * Capture a single spectrum frame.
   *
   * @param includeTm30 When true, requests the larger 0x34 frame that includes
   *                    TM-30 colour rendering metrics.
   * @param timeoutMs   Per-call timeout override. The default scales with the
   *                    currently-configured exposure time when known.
   */
  async captureSingle(includeTm30 = false, timeoutMs?: number): Promise<SpectrumFrame> {
    if (this.streamingMode !== null) {
      throw new ProtocolError('cannot captureSingle while streaming');
    }
    const cmdType = includeTm30 ? CMD.CaptureSingleWithTm30 : CMD.CaptureSingleNoTm30;
    const frame = includeTm30 ? buildCaptureSingleWithTm30() : buildCaptureSingleNoTm30();
    const { validData } = await this.request(frame, cmdType, timeoutMs ?? 5000);
    return decodeSpectrumFrame(validData, includeTm30);
  }

  /**
   * Begin a streaming capture session. Frames are emitted as `'frame'` events
   * until {@link stopStreaming} is called.
   */
  async startStreaming(includeTm30 = false): Promise<void> {
    if (this.streamingMode !== null) {
      throw new ProtocolError('streaming already active');
    }
    // Wait for an exclusive lock so any pending request finishes first.
    await this.acquireLock();
    try {
      const cmdType = includeTm30 ? CMD.StartStreamWithTm30 : CMD.StartStreamNoTm30;
      const frame = includeTm30 ? buildStartStreamWithTm30() : buildStartStreamNoTm30();
      this.streamingMode = cmdType;
      this.stopping = false;
      await this.writeBytes(frame);
    } finally {
      this.releaseLock();
    }
  }

  /**
   * Stop a streaming capture. Sends the stop command and continues to drain
   * already-buffered frames silently (per PROTOCOL.md §8 point 2 — the device
   * may have one or two more frames queued at the moment the stop arrives).
   */
  async stopStreaming(): Promise<void> {
    if (this.streamingMode === null) {
      return;
    }
    this.stopping = true;
    await this.writeBytes(buildStopCapture());
    // Give the device a moment to flush trailing frames.
    await new Promise((r) => setTimeout(r, 100));
    this.streamingMode = null;
    this.stopping = false;
    // Anything left in rxBuffer at this point is unwanted; drop it.
    this.rxBuffer = Buffer.alloc(0);
  }

  /** True while a streaming capture is active. */
  isStreaming(): boolean {
    return this.streamingMode !== null;
  }

  /**
   * Upload a complete efficiency curve. Sends the start packet, the float
   * payload in ≤247-float chunks, and the verify-and-compute command.
   *
   * Per PROTOCOL.md §8 point 5, no intermediate response is expected; the
   * function resolves once 0x27's success status is received.
   */
  async uploadEfficiencyCurve(
    ratios: ArrayLike<number> | Float32Array,
    options: { verifyTimeoutMs?: number } = {},
  ): Promise<void> {
    if (this.streamingMode !== null) {
      throw new ProtocolError('cannot upload efficiency curve while streaming');
    }
    const float32 =
      ratios instanceof Float32Array ? ratios : Float32Array.from(ratios as ArrayLike<number>);
    await this.writeBytes(buildSendEfficiencyCurveStart());
    for (let i = 0; i < float32.length; i += EFFICIENCY_CHUNK_FLOATS) {
      const chunk = float32.subarray(i, i + EFFICIENCY_CHUNK_FLOATS);
      await this.writeBytes(buildSendEfficiencyCurveChunk(chunk));
    }
    await this.verifyAndComputeEfficiencyCurve(options.verifyTimeoutMs ?? 10000);
  }

  /** Trigger flash write & verify of the previously uploaded curve. */
  async verifyAndComputeEfficiencyCurve(timeoutMs = 10000): Promise<void> {
    const { validData } = await this.request(
      buildVerifyEfficiencyCurve(),
      CMD.VerifyEfficiencyCurve,
      timeoutMs,
    );
    checkSetStatus(validData, CMD.VerifyEfficiencyCurve);
  }

  /** Restore the factory-default efficiency curve. */
  async resetEfficiencyCurve(): Promise<void> {
    const { validData } = await this.request(buildResetEfficiencyCurve(), CMD.ResetEfficiencyCurve);
    checkSetStatus(validData, CMD.ResetEfficiencyCurve);
  }

  // -------------------------------------------------------------------------
  // Internals
  // -------------------------------------------------------------------------

  /**
   * Run a single request/response exchange under the mutex. Returns the
   * parsed envelope (totalLen / dataType / validData).
   */
  private async request(
    requestBytes: Buffer,
    expectedCmdType: number,
    timeoutMs?: number,
  ): Promise<{ totalLen: number; dataType: number; validData: Buffer }> {
    if (this.closed) {
      throw new ProtocolError('device is closed');
    }
    if (this.streamingMode !== null) {
      throw new ProtocolError('cannot issue request while streaming');
    }
    await this.acquireLock();
    try {
      const responsePromise = new Promise<Buffer>((resolve, reject) => {
        const timer = setTimeout(() => {
          if (this.inflight) {
            this.inflight = undefined;
          }
          reject(
            new TimeoutError(
              `timed out after ${
                timeoutMs ?? this.defaultTimeoutMs
              }ms waiting for response to cmd 0x${expectedCmdType.toString(16)}`,
            ),
          );
        }, timeoutMs ?? this.defaultTimeoutMs);
        this.inflight = {
          expectedCmdType,
          timer,
          resolve: (frame) => {
            clearTimeout(timer);
            this.inflight = undefined;
            resolve(frame);
          },
          reject: (err) => {
            clearTimeout(timer);
            this.inflight = undefined;
            reject(err);
          },
        };
      });

      await this.writeBytes(requestBytes);
      const responseFrame = await responsePromise;
      return parseResponse(responseFrame, expectedCmdType);
    } finally {
      this.releaseLock();
    }
  }

  private writeBytes(bytes: Buffer): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.port.write(bytes, (err) => {
          if (err) reject(err);
          else resolve();
        });
      } catch (err) {
        reject(err as Error);
      }
    });
  }

  // --- mutex ---------------------------------------------------------------

  private locked = false;

  private acquireLock(): Promise<void> {
    if (!this.locked) {
      this.locked = true;
      return Promise.resolve();
    }
    return new Promise<void>((resolve) => {
      this.waitQueue.push(() => {
        this.locked = true;
        resolve();
      });
    });
  }

  private releaseLock(): void {
    this.locked = false;
    const next = this.waitQueue.shift();
    if (next) next();
  }

  // --- rx event handlers ---------------------------------------------------

  private readonly onData = (chunk: Buffer): void => {
    this.rxBuffer = this.rxBuffer.length === 0 ? chunk : Buffer.concat([this.rxBuffer, chunk]);
    this.drain();
  };

  private readonly onClose = (): void => {
    this.emit('close');
  };

  private readonly onError = (err: Error): void => {
    if (this.inflight) {
      this.inflight.reject(err);
    } else {
      this.emit('error', err);
    }
  };

  /**
   * Pull complete frames out of {@link rxBuffer} and dispatch them either to
   * the inflight request (one-shot commands) or as `'frame'` events (streaming).
   */
  private drain(): void {
    while (this.rxBuffer.length >= 5) {
      // Resync to a header byte if we are not already aligned.
      if (this.rxBuffer[0] !== HEADER_RESP_0 || this.rxBuffer[1] !== HEADER_RESP_1) {
        const idx = this.findHeader(this.rxBuffer);
        if (idx < 0) {
          // No header found at all — wait for more data.
          this.rxBuffer = this.rxBuffer.subarray(this.rxBuffer.length - 1);
          return;
        }
        this.rxBuffer = this.rxBuffer.subarray(idx);
        if (this.rxBuffer.length < 5) return;
      }
      let totalLen: number | undefined;
      try {
        totalLen = peekTotalLen(this.rxBuffer);
      } catch (err) {
        // Header mismatch — drop one byte and keep scanning.
        this.rxBuffer = this.rxBuffer.subarray(1);
        if (this.inflight) {
          this.inflight.reject(err as Error);
        } else {
          this.emit('error', err as Error);
        }
        continue;
      }
      if (totalLen === undefined) return;
      // Bound totalLen before trusting it. A false CC 81 sequence inside
      // payload data would otherwise yield a huge length, causing us to wait
      // forever for bytes that never come while rxBuffer grows unbounded (up
      // to a 16.7 MB uint24). If the length is implausible the header is bogus:
      // drop one byte and resync, mirroring Python (1 MB cap) / C++ (64 KiB).
      if (totalLen < FRAME_OVERHEAD || totalLen > MAX_FRAME_LEN) {
        this.rxBuffer = this.rxBuffer.subarray(1);
        const err = new ProtocolError(
          `implausible totalLen=${totalLen}; resynchronising`,
        );
        if (this.inflight) {
          this.inflight.reject(err);
        } else {
          this.emit('error', err);
        }
        continue;
      }
      if (this.rxBuffer.length < totalLen) return;
      const frame = this.rxBuffer.subarray(0, totalLen);
      this.rxBuffer = this.rxBuffer.subarray(totalLen);
      this.handleFrame(Buffer.from(frame));
    }
  }

  private findHeader(buf: Buffer): number {
    for (let i = 0; i < buf.length - 1; i++) {
      if (buf[i] === HEADER_RESP_0 && buf[i + 1] === HEADER_RESP_1) return i;
    }
    return -1;
  }

  private handleFrame(frame: Buffer): void {
    // Streaming path: dispatch as a 'frame' event (unless we are mid-stop).
    if (this.streamingMode !== null) {
      try {
        const { validData, dataType } = parseResponse(frame);
        if (dataType !== this.streamingMode) {
          // A stray response to a non-stream command — pass to inflight if any.
          if (this.inflight && dataType === this.inflight.expectedCmdType) {
            this.inflight.resolve(frame);
            return;
          }
          this.emit(
            'error',
            new ProtocolError(
              `streaming dataType mismatch: expected 0x${this.streamingMode.toString(
                16,
              )}, got 0x${dataType.toString(16)}`,
            ),
          );
          return;
        }
        if (this.stopping) {
          // Drop trailing frames silently.
          return;
        }
        const includeTm30 = dataType === CMD.StartStreamWithTm30;
        const spectrum = decodeSpectrumFrame(validData, includeTm30);
        this.emit('frame', spectrum);
      } catch (err) {
        this.emit('error', err as Error);
      }
      return;
    }

    // Non-streaming path: hand the raw frame to the pending request.
    if (this.inflight) {
      this.inflight.resolve(frame);
    } else {
      // No-one expecting it; ignore but emit for observability.
      this.emit(
        'error',
        new ProtocolError(`unexpected response frame (${frame.length} bytes) with no in-flight request`),
      );
    }
  }
}
