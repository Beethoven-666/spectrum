/**
 * Pure protocol encoding / decoding.
 *
 * Every function here is side-effect free and works on Node `Buffer`s.
 * Byte layout, command numbering and checksum algorithm are defined in
 * docs/PROTOCOL.md — this file is a direct implementation of that document.
 */

import { DeviceError, ProtocolError } from './errors.js';
import type {
  BlueHazardParams,
  DeviceInfo,
  NirParams,
  PhotometricParams,
  PlantParams,
  SpectrumFrame,
  Tm30Params,
  WavelengthRange,
} from './types.js';
import { CieMode, DeviceStatus, ExposureMode, ExposureStatus, WorkingMode } from './types.js';

// ---------------------------------------------------------------------------
// Frame constants
// ---------------------------------------------------------------------------

export const HEADER_CMD_0 = 0xcc;
export const HEADER_CMD_1 = 0x01;
export const HEADER_RESP_0 = 0xcc;
export const HEADER_RESP_1 = 0x81;
export const FOOTER_0 = 0x0d;
export const FOOTER_1 = 0x0a;

/** Frame overhead in bytes: 2 header + 3 totalLen + 1 cmd/data type + 1 checksum + 2 footer. */
export const FRAME_OVERHEAD = 9;

// ---------------------------------------------------------------------------
// Command codes (cmdType byte)
// ---------------------------------------------------------------------------

export const CMD = {
  StopCapture: 0x04,
  GetDeviceInfo: 0x08,
  SetExposureMode: 0x0a,
  GetExposureMode: 0x0b,
  SetExposureTime: 0x0c,
  GetExposureTime: 0x0d,
  GetWavelengthRange: 0x0f,
  SetMaxExposureTime: 0x13,
  GetMaxExposureTime: 0x14,
  SendEfficiencyCurve: 0x23,
  ResetEfficiencyCurve: 0x25,
  VerifyEfficiencyCurve: 0x27,
  CaptureSingleNoTm30: 0x32,
  StartStreamNoTm30: 0x33,
  CaptureSingleWithTm30: 0x34,
  StartStreamWithTm30: 0x35,
  SetCieMode: 0x36,
  GetCieMode: 0x37,
  EnterExitSleep: 0x40,
  SetWorkingMode: 0x41,
} as const satisfies Record<string, number>;

export type CmdCode = (typeof CMD)[keyof typeof CMD];

// ---------------------------------------------------------------------------
// Low-level helpers
// ---------------------------------------------------------------------------

/** Compute a single-byte sum modulo 256 over the supplied byte range. */
export function checksum(bytes: Buffer | Uint8Array, start = 0, end?: number): number {
  const stop = end ?? bytes.length;
  let sum = 0;
  for (let i = start; i < stop; i++) {
    sum = (sum + bytes[i]!) & 0xff;
  }
  return sum;
}

/** Write an unsigned 24-bit little-endian integer into `buf` at `offset`. */
export function writeUInt24LE(buf: Buffer, value: number, offset: number): void {
  buf[offset] = value & 0xff;
  buf[offset + 1] = (value >>> 8) & 0xff;
  buf[offset + 2] = (value >>> 16) & 0xff;
}

/** Read an unsigned 24-bit little-endian integer from `buf` at `offset`. */
export function readUInt24LE(buf: Buffer, offset: number): number {
  return buf[offset]! | (buf[offset + 1]! << 8) | (buf[offset + 2]! << 16);
}

// ---------------------------------------------------------------------------
// Command builder
// ---------------------------------------------------------------------------

/**
 * Build a complete command frame given the cmdType and (possibly empty) cmdData.
 *
 * Returns a fresh `Buffer` of length `9 + cmdData.length`.
 */
export function buildCommand(cmdType: number, cmdData: Buffer | Uint8Array = Buffer.alloc(0)): Buffer {
  const totalLen = FRAME_OVERHEAD + cmdData.length;
  const buf = Buffer.alloc(totalLen);
  buf[0] = HEADER_CMD_0;
  buf[1] = HEADER_CMD_1;
  writeUInt24LE(buf, totalLen, 2);
  buf[5] = cmdType & 0xff;
  if (cmdData.length > 0) {
    // Buffer.from copies; OK for small command payloads.
    Buffer.from(cmdData).copy(buf, 6);
  }
  // Checksum covers bytes [0 .. 6+N-1] (i.e. everything before the checksum slot).
  const checksumOffset = 6 + cmdData.length;
  buf[checksumOffset] = checksum(buf, 0, checksumOffset);
  buf[checksumOffset + 1] = FOOTER_0;
  buf[checksumOffset + 2] = FOOTER_1;
  return buf;
}

// ---------------------------------------------------------------------------
// Specific command constructors (one per command in PROTOCOL.md §3)
// ---------------------------------------------------------------------------

export function buildStopCapture(): Buffer {
  return buildCommand(CMD.StopCapture);
}

export function buildGetDeviceInfo(): Buffer {
  // cmdData = 0x18 (expected length = 24)
  return buildCommand(CMD.GetDeviceInfo, Buffer.from([0x18]));
}

export function buildSetExposureMode(mode: ExposureMode): Buffer {
  return buildCommand(CMD.SetExposureMode, Buffer.from([mode & 0xff]));
}

export function buildGetExposureMode(): Buffer {
  return buildCommand(CMD.GetExposureMode);
}

export function buildSetExposureTime(us: number): Buffer {
  const data = Buffer.alloc(4);
  data.writeUInt32LE(us >>> 0, 0);
  return buildCommand(CMD.SetExposureTime, data);
}

export function buildGetExposureTime(): Buffer {
  return buildCommand(CMD.GetExposureTime);
}

export function buildGetWavelengthRange(): Buffer {
  return buildCommand(CMD.GetWavelengthRange);
}

export function buildSetMaxExposureTime(us: number): Buffer {
  const data = Buffer.alloc(4);
  data.writeUInt32LE(us >>> 0, 0);
  return buildCommand(CMD.SetMaxExposureTime, data);
}

export function buildGetMaxExposureTime(): Buffer {
  return buildCommand(CMD.GetMaxExposureTime);
}

export function buildSendEfficiencyCurveStart(): Buffer {
  // cmdData = 0x04 marks the start packet.
  return buildCommand(CMD.SendEfficiencyCurve, Buffer.from([0x04]));
}

/**
 * Build a single data packet of the efficiency curve upload.
 * `chunk` is a Float32 view (or a Buffer of float bytes). The caller is
 * responsible for chunking the entire ratio array into packets whose payload
 * is ≤ 990 bytes (247 floats) as required by PROTOCOL.md §3.16.
 */
export function buildSendEfficiencyCurveChunk(chunk: Buffer | Uint8Array | Float32Array): Buffer {
  let payload: Buffer;
  if (chunk instanceof Float32Array) {
    payload = Buffer.from(chunk.buffer, chunk.byteOffset, chunk.byteLength);
  } else if (Buffer.isBuffer(chunk)) {
    payload = chunk;
  } else {
    payload = Buffer.from(chunk);
  }
  return buildCommand(CMD.SendEfficiencyCurve, payload);
}

export function buildResetEfficiencyCurve(): Buffer {
  return buildCommand(CMD.ResetEfficiencyCurve);
}

export function buildVerifyEfficiencyCurve(): Buffer {
  return buildCommand(CMD.VerifyEfficiencyCurve);
}

export function buildCaptureSingleNoTm30(): Buffer {
  return buildCommand(CMD.CaptureSingleNoTm30);
}

export function buildStartStreamNoTm30(): Buffer {
  return buildCommand(CMD.StartStreamNoTm30);
}

export function buildCaptureSingleWithTm30(): Buffer {
  return buildCommand(CMD.CaptureSingleWithTm30);
}

export function buildStartStreamWithTm30(): Buffer {
  return buildCommand(CMD.StartStreamWithTm30);
}

export function buildSetCieMode(mode: CieMode): Buffer {
  return buildCommand(CMD.SetCieMode, Buffer.from([mode & 0xff]));
}

export function buildGetCieMode(): Buffer {
  return buildCommand(CMD.GetCieMode);
}

export function buildEnterExitSleep(): Buffer {
  return buildCommand(CMD.EnterExitSleep);
}

export function buildSetWorkingMode(mode: WorkingMode): Buffer {
  return buildCommand(CMD.SetWorkingMode, Buffer.from([mode & 0xff]));
}

// ---------------------------------------------------------------------------
// Response parsing
// ---------------------------------------------------------------------------

/** Parsed response frame envelope (without per-command interpretation). */
export interface ParsedResponse {
  totalLen: number;
  dataType: number;
  validData: Buffer;
}

/**
 * Validate a fully received response frame (header, totalLen, footer, checksum)
 * and return the envelope and validData slice.
 *
 * Optionally checks that `dataType` equals `expectedCmdType`; pass undefined to
 * skip that check (useful for streaming where the caller already knows the type).
 */
export function parseResponse(frame: Buffer, expectedCmdType?: number): ParsedResponse {
  if (frame.length < FRAME_OVERHEAD) {
    throw new ProtocolError(`frame too short: ${frame.length} bytes (min ${FRAME_OVERHEAD})`);
  }
  if (frame[0] !== HEADER_RESP_0 || frame[1] !== HEADER_RESP_1) {
    throw new ProtocolError(
      `bad response header: 0x${frame[0]!.toString(16)} 0x${frame[1]!.toString(16)}`,
    );
  }
  const totalLen = readUInt24LE(frame, 2);
  if (totalLen !== frame.length) {
    throw new ProtocolError(
      `totalLen mismatch: header says ${totalLen} but frame is ${frame.length} bytes`,
    );
  }
  const checksumOffset = frame.length - 3;
  if (frame[frame.length - 2] !== FOOTER_0 || frame[frame.length - 1] !== FOOTER_1) {
    throw new ProtocolError('bad response footer (expected 0x0D 0x0A)');
  }
  const expected = checksum(frame, 0, checksumOffset);
  const actual = frame[checksumOffset]!;
  if (expected !== actual) {
    throw new ProtocolError(
      `checksum mismatch: computed 0x${expected.toString(16)}, got 0x${actual.toString(16)}`,
    );
  }
  const dataType = frame[5]!;
  if (expectedCmdType !== undefined && dataType !== expectedCmdType) {
    throw new ProtocolError(
      `dataType mismatch: expected 0x${expectedCmdType.toString(16)}, got 0x${dataType.toString(16)}`,
    );
  }
  // validData spans bytes 6 .. checksumOffset (exclusive).
  const validData = frame.subarray(6, checksumOffset);
  return { totalLen, dataType, validData };
}

/**
 * Treat the validData as a single device status byte. Throws DeviceError for
 * 0x15 and 0xFF, returns silently on 0x00.
 */
export function checkSetStatus(validData: Buffer, cmdType: number): void {
  if (validData.length !== 1) {
    throw new ProtocolError(
      `expected 1-byte status for cmd 0x${cmdType.toString(16)}, got ${validData.length}`,
    );
  }
  const status = validData[0]!;
  switch (status) {
    case DeviceStatus.Success:
      return;
    case DeviceStatus.InvalidCommand:
      throw new DeviceError(status, 'invalid command', cmdType);
    case DeviceStatus.UnsupportedOrOutOfRange:
      throw new DeviceError(status, 'unsupported or out of range', cmdType);
    default:
      throw new ProtocolError(
        `unknown status byte 0x${status.toString(16)} for cmd 0x${cmdType.toString(16)}`,
      );
  }
}

// ---------------------------------------------------------------------------
// Per-response decoders
// ---------------------------------------------------------------------------

export function decodeDeviceInfo(validData: Buffer): DeviceInfo {
  if (validData.length !== 24) {
    throw new ProtocolError(`expected 24-byte SN, got ${validData.length}`);
  }
  return { serialNumber: validData.toString('ascii') };
}

export function decodeWavelengthRange(validData: Buffer): WavelengthRange {
  if (validData.length !== 4) {
    throw new ProtocolError(`expected 4-byte wavelength range, got ${validData.length}`);
  }
  return {
    start: validData.readUInt16LE(0),
    end: validData.readUInt16LE(2),
  };
}

export function decodeExposureMode(validData: Buffer): ExposureMode {
  if (validData.length !== 1) {
    throw new ProtocolError(`expected 1-byte exposure mode, got ${validData.length}`);
  }
  const v = validData[0]!;
  if (v !== ExposureMode.Manual && v !== ExposureMode.Auto) {
    throw new ProtocolError(`unknown exposure mode byte 0x${v.toString(16)}`);
  }
  return v;
}

export function decodeExposureTimeUs(validData: Buffer): number {
  if (validData.length !== 4) {
    throw new ProtocolError(`expected 4-byte exposure time, got ${validData.length}`);
  }
  return validData.readUInt32LE(0);
}

export function decodeCieMode(validData: Buffer): CieMode {
  if (validData.length !== 1) {
    throw new ProtocolError(`expected 1-byte CIE mode, got ${validData.length}`);
  }
  const v = validData[0]!;
  if (v < 0 || v > 3) {
    throw new ProtocolError(`unknown CIE mode byte 0x${v.toString(16)}`);
  }
  return v as CieMode;
}

// ---------------------------------------------------------------------------
// SpectrumFrame decoder
// ---------------------------------------------------------------------------

/**
 * Decode the `validData` portion of a SpectrumFrame response (cmdType 0x32/0x33
 * or 0x34/0x35). `includeTm30` selects between the two layouts (PROTOCOL.md §4).
 *
 * `M` (number of raw spectrum samples) is derived from the remaining bytes after
 * the fixed-layout fields.
 */
export function decodeSpectrumFrame(validData: Buffer, includeTm30: boolean): SpectrumFrame {
  const fixedLen = includeTm30 ? 2731 : 275;
  if (validData.length < fixedLen) {
    throw new ProtocolError(
      `spectrum frame too short: need at least ${fixedLen} bytes, got ${validData.length}`,
    );
  }
  const tailBytes = validData.length - fixedLen;
  if (tailBytes < 0 || tailBytes % 2 !== 0) {
    throw new ProtocolError(`rawSpectrum byte count not divisible by 2: ${tailBytes}`);
  }
  const m = tailBytes / 2;

  const exposureStatus = validData[0]! as ExposureStatus;
  const exposureTimeUs = validData.readUInt32LE(1);

  // photometric: offset 5, 47 floats
  const photometric = decodePhotometric(validData, 5);
  // blueHazard: offset 193, 1 float
  const blueHazard: BlueHazardParams = { Eb: validData.readFloatLE(193) };
  // nir: offset 197, 3 floats
  const nir: NirParams = {
    redEe: validData.readFloatLE(197),
    nirEeA: validData.readFloatLE(201),
    nirEeB: validData.readFloatLE(205),
  };
  // plant: offset 209, 16 floats
  const plant = decodePlant(validData, 209);

  let tm30: Tm30Params | undefined;
  let coeffOffset: number;
  let rawOffset: number;
  if (includeTm30) {
    // tm30: offset 273, 614 floats (2456 bytes)
    tm30 = decodeTm30(validData, 273);
    coeffOffset = 2729;
    rawOffset = 2731;
  } else {
    coeffOffset = 273;
    rawOffset = 275;
  }

  const spectrumCoefficient = validData.readInt16LE(coeffOffset);
  const rawSpectrum = new Uint16Array(m);
  // Use a DataView over the underlying ArrayBuffer for safe little-endian reads,
  // since the Uint16Array constructor is host-endian.
  const view = new DataView(validData.buffer, validData.byteOffset, validData.byteLength);
  for (let i = 0; i < m; i++) {
    rawSpectrum[i] = view.getUint16(rawOffset + 2 * i, true);
  }
  const divisor = Math.pow(10, spectrumCoefficient);
  const actualSpectrum = new Float32Array(m);
  for (let i = 0; i < m; i++) {
    actualSpectrum[i] = rawSpectrum[i]! / divisor;
  }

  return {
    exposureStatus,
    exposureTimeUs,
    photometric,
    blueHazard,
    nir,
    plant,
    tm30,
    spectrumCoefficient,
    rawSpectrum,
    actualSpectrum,
  };
}

function decodePhotometric(buf: Buffer, offset: number): PhotometricParams {
  // Order matches PROTOCOL.md §5.1 exactly.
  return {
    X: buf.readFloatLE(offset + 0 * 4),
    Y: buf.readFloatLE(offset + 1 * 4),
    Z: buf.readFloatLE(offset + 2 * 4),
    x: buf.readFloatLE(offset + 3 * 4),
    y: buf.readFloatLE(offset + 4 * 4),
    uk: buf.readFloatLE(offset + 5 * 4),
    vk: buf.readFloatLE(offset + 6 * 4),
    u_prime: buf.readFloatLE(offset + 7 * 4),
    v_prime: buf.readFloatLE(offset + 8 * 4),
    CCT: buf.readFloatLE(offset + 9 * 4),
    Nit: buf.readFloatLE(offset + 10 * 4),
    r_ratio: buf.readFloatLE(offset + 11 * 4),
    g_ratio: buf.readFloatLE(offset + 12 * 4),
    b_ratio: buf.readFloatLE(offset + 13 * 4),
    DUV: buf.readFloatLE(offset + 14 * 4),
    Ra: buf.readFloatLE(offset + 15 * 4),
    R1: buf.readFloatLE(offset + 16 * 4),
    R2: buf.readFloatLE(offset + 17 * 4),
    R3: buf.readFloatLE(offset + 18 * 4),
    R4: buf.readFloatLE(offset + 19 * 4),
    R5: buf.readFloatLE(offset + 20 * 4),
    R6: buf.readFloatLE(offset + 21 * 4),
    R7: buf.readFloatLE(offset + 22 * 4),
    R8: buf.readFloatLE(offset + 23 * 4),
    R9: buf.readFloatLE(offset + 24 * 4),
    R10: buf.readFloatLE(offset + 25 * 4),
    R11: buf.readFloatLE(offset + 26 * 4),
    R12: buf.readFloatLE(offset + 27 * 4),
    R13: buf.readFloatLE(offset + 28 * 4),
    R14: buf.readFloatLE(offset + 29 * 4),
    R15: buf.readFloatLE(offset + 30 * 4),
    Lp: buf.readFloatLE(offset + 31 * 4),
    HW: buf.readFloatLE(offset + 32 * 4),
    Ld: buf.readFloatLE(offset + 33 * 4),
    purity: buf.readFloatLE(offset + 34 * 4),
    SP: buf.readFloatLE(offset + 35 * 4),
    SDCM_k: buf.readFloatLE(offset + 36 * 4),
    k: buf.readFloatLE(offset + 37 * 4),
    lux: buf.readFloatLE(offset + 38 * 4),
    Ee: buf.readFloatLE(offset + 39 * 4),
    fc: buf.readFloatLE(offset + 40 * 4),
    CQS: buf.readFloatLE(offset + 41 * 4),
    GAI_EES: buf.readFloatLE(offset + 42 * 4),
    GAI_BB_8: buf.readFloatLE(offset + 43 * 4),
    GAI_BB_15: buf.readFloatLE(offset + 44 * 4),
    EML: buf.readFloatLE(offset + 45 * 4),
    M_EDI: buf.readFloatLE(offset + 46 * 4),
  };
}

function decodePlant(buf: Buffer, offset: number): PlantParams {
  return {
    PAR: buf.readFloatLE(offset + 0 * 4),
    Eca: buf.readFloatLE(offset + 1 * 4),
    Ecb: buf.readFloatLE(offset + 2 * 4),
    Eb: buf.readFloatLE(offset + 3 * 4),
    Ey: buf.readFloatLE(offset + 4 * 4),
    Er: buf.readFloatLE(offset + 5 * 4),
    Erb_ratio: buf.readFloatLE(offset + 6 * 4),
    PPFD: buf.readFloatLE(offset + 7 * 4),
    PPFDb: buf.readFloatLE(offset + 8 * 4),
    PPFDy: buf.readFloatLE(offset + 9 * 4),
    PPFDr: buf.readFloatLE(offset + 10 * 4),
    PPFDfr: buf.readFloatLE(offset + 11 * 4),
    PPFDr_ratio: buf.readFloatLE(offset + 12 * 4),
    PPFDy_ratio: buf.readFloatLE(offset + 13 * 4),
    PPFDb_ratio: buf.readFloatLE(offset + 14 * 4),
    YPFD: buf.readFloatLE(offset + 15 * 4),
  };
}

function decodeTm30(buf: Buffer, offset: number): Tm30Params {
  // Order matches PROTOCOL.md §5.5 — 614 floats total.
  const readFloatArray = (start: number, count: number): number[] => {
    const out = new Array<number>(count);
    for (let i = 0; i < count; i++) {
      out[i] = buf.readFloatLE(start + i * 4);
    }
    return out;
  };
  const readPairArray = (start: number, pairs: number): number[][] => {
    const out = new Array<number[]>(pairs);
    for (let i = 0; i < pairs; i++) {
      out[i] = [buf.readFloatLE(start + i * 8), buf.readFloatLE(start + i * 8 + 4)];
    }
    return out;
  };

  const referenceSpectrum = readFloatArray(offset + 0, 401);
  const Eab = readFloatArray(offset + 401 * 4, 99);
  const Rf = buf.readFloatLE(offset + 500 * 4);
  const Rg = buf.readFloatLE(offset + 501 * 4);
  const chromaShift = readFloatArray(offset + 502 * 4, 16);
  const hueShift = readFloatArray(offset + 518 * 4, 16);
  const colorFidelity = readFloatArray(offset + 534 * 4, 16);
  const cesAbTest = readPairArray(offset + 550 * 4, 16);
  const cesAbReference = readPairArray(offset + 582 * 4, 16);

  return {
    referenceSpectrum,
    Eab,
    Rf,
    Rg,
    chromaShift,
    hueShift,
    colorFidelity,
    cesAbTest,
    cesAbReference,
  };
}

// ---------------------------------------------------------------------------
// Helpers for incremental / streaming response framing
// ---------------------------------------------------------------------------

/**
 * Look at the first six bytes of a buffer (which must be the start of a
 * response frame) and return the expected total frame length. Returns
 * `undefined` if not enough bytes are buffered yet.
 */
export function peekTotalLen(buf: Buffer): number | undefined {
  if (buf.length < 5) {
    return undefined;
  }
  if (buf[0] !== HEADER_RESP_0 || buf[1] !== HEADER_RESP_1) {
    throw new ProtocolError(
      `bad response header at peek: 0x${buf[0]!.toString(16)} 0x${buf[1]!.toString(16)}`,
    );
  }
  return readUInt24LE(buf, 2);
}
