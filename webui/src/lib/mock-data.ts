/**
 * Synthetic mock data + response-frame builders.
 *
 * Generates plausible 5500K warm-white LED spectra plus all 47 photometric /
 * 1 blue hazard / 3 NIR / 16 plant / 614 TM-30 parameters, then encodes them
 * into validData buffers and wraps them in valid response frames the @h1/sdk
 * parser can decode.
 *
 * Every value gets a small per-frame jitter so streams look alive.
 */

import { Buffer } from 'node:buffer';

import {
  protocol,
  ExposureMode,
  ExposureStatus,
  CieMode,
  WorkingMode,
} from '@h1/sdk';

const HEADER_RESP_0 = 0xcc;
const HEADER_RESP_1 = 0x81;
const FOOTER_0 = 0x0d;
const FOOTER_1 = 0x0a;

/**
 * Wavelength range used by the mock (340..1050 nm inclusive — 711 samples).
 * Mirrors the typical H1 device.
 */
export const MOCK_WL_START = 340;
export const MOCK_WL_END = 1050;
export const MOCK_SAMPLE_COUNT = MOCK_WL_END - MOCK_WL_START + 1;

/** N=2 → actual = raw / 100 (per PROTOCOL §4.3). */
export const MOCK_SPECTRUM_COEFFICIENT = 2;

/** 24-byte ASCII SN. */
export const MOCK_SERIAL_NUMBER = 'H1MOCK0000000000000-DEV';

/* -------------------------------------------------------------------------- */
/* Internal frame helper                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Wrap `validData` in a complete response frame (header / totalLen / dataType /
 * checksum / footer). Mirrors {@link protocol.buildCommand} but uses the response
 * header bytes.
 */
function buildResponseFrame(dataType: number, validData: Buffer): Buffer {
  const totalLen = protocol.FRAME_OVERHEAD + validData.length;
  const buf = Buffer.alloc(totalLen);
  buf[0] = HEADER_RESP_0;
  buf[1] = HEADER_RESP_1;
  protocol.writeUInt24LE(buf, totalLen, 2);
  buf[5] = dataType & 0xff;
  validData.copy(buf, 6);
  const checksumOffset = 6 + validData.length;
  buf[checksumOffset] = protocol.checksum(buf, 0, checksumOffset);
  buf[checksumOffset + 1] = FOOTER_0;
  buf[checksumOffset + 2] = FOOTER_1;
  return buf;
}

/** Build a 1-byte status response (used for set-style commands). */
function buildStatusResponse(cmdType: number, status = 0x00): Buffer {
  return buildResponseFrame(cmdType, Buffer.from([status]));
}

/* -------------------------------------------------------------------------- */
/* Spectrum generator                                                         */
/* -------------------------------------------------------------------------- */

/** Simple gaussian. */
function gaussian(x: number, mu: number, sigma: number, height: number): number {
  const d = (x - mu) / sigma;
  return height * Math.exp(-0.5 * d * d);
}

/**
 * Generate a plausible warm-white LED spectrum (441nm blue + 555nm yellow-green
 * broad) sampled at 1nm steps from MOCK_WL_START..MOCK_WL_END.
 *
 * Adds ±2% per-sample jitter so successive frames look distinct.
 */
function generateActualSpectrum(): Float32Array {
  const out = new Float32Array(MOCK_SAMPLE_COUNT);
  for (let i = 0; i < MOCK_SAMPLE_COUNT; i++) {
    const lambda = MOCK_WL_START + i;
    let v = 0;
    v += gaussian(lambda, 441, 14, 5500); // blue peak
    v += gaussian(lambda, 555, 55, 8000); // yellow-green broad
    v += gaussian(lambda, 600, 90, 4500); // red shoulder
    v += gaussian(lambda, 720, 80, 700);  // far-red tail
    v += gaussian(lambda, 850, 70, 200);  // small NIR shoulder
    // baseline noise
    v += 5 + Math.random() * 3;
    // per-frame jitter
    v *= 1 + (Math.random() - 0.5) * 0.04;
    out[i] = Math.max(0, v);
  }
  return out;
}

/* -------------------------------------------------------------------------- */
/* Parameter generators (47 + 1 + 3 + 16 + 614 floats)                        */
/* -------------------------------------------------------------------------- */

function jitter(base: number, pct: number): number {
  return base * (1 + (Math.random() - 0.5) * pct);
}

function jitterAbs(base: number, abs: number): number {
  return base + (Math.random() - 0.5) * abs * 2;
}

function generatePhotometric(): Float32Array {
  // Layout per PROTOCOL.md §5.1 — exactly 47 floats.
  const cct = jitterAbs(5500, 50);
  const lux = jitterAbs(500, 10);
  const X = 0.95 * lux;
  const Y = 1.0 * lux;
  const Z = 1.09 * lux;
  const sum = X + Y + Z;
  const x = X / sum;
  const y = Y / sum;
  const denomCie1960 = -2 * x + 12 * y + 3;
  const uk = (4 * x) / denomCie1960;
  const vk = (6 * y) / denomCie1960;
  const u_prime = uk;
  const v_prime = 1.5 * vk;
  return new Float32Array([
    X, Y, Z, x, y, uk, vk, u_prime, v_prime, cct,
    jitter(500, 0.05),    // Nit
    jitter(33.5, 0.02),   // r_ratio %
    jitter(38.2, 0.02),   // g_ratio %
    jitter(28.3, 0.02),   // b_ratio %
    jitterAbs(0.002, 0.001), // DUV
    jitterAbs(85, 2),     // Ra
    jitterAbs(87, 3), jitterAbs(92, 2), jitterAbs(94, 2), jitterAbs(89, 3),
    jitterAbs(86, 3), jitterAbs(88, 2), jitterAbs(93, 2), jitterAbs(75, 4),
    jitterAbs(45, 5), jitterAbs(82, 3), jitterAbs(70, 4), jitterAbs(88, 3),
    jitterAbs(91, 2), jitterAbs(80, 3), jitterAbs(83, 3), // R1..R15
    jitterAbs(555, 5),    // Lp peak nm
    jitterAbs(120, 4),    // HW FWHM nm
    jitterAbs(580, 6),    // Ld dominant nm
    jitterAbs(55, 3),     // purity %
    jitter(1.43, 0.02),   // SP
    jitterAbs(3.5, 0.4),  // SDCM_k
    jitterAbs(5500, 30),  // k
    lux,                  // lux
    jitter(1.65, 0.03),   // Ee W/m²
    jitter(46.45, 0.03),  // fc
    jitterAbs(83, 3),     // CQS
    jitter(0.88, 0.02),   // GAI_EES
    jitter(0.83, 0.02),   // GAI_BB_8
    jitter(0.86, 0.02),   // GAI_BB_15
    jitter(400, 0.04),    // EML
    jitter(380, 0.04),    // M_EDI
  ]);
}

function generateBlueHazard(): Float32Array {
  return new Float32Array([jitter(0.18, 0.05)]); // Eb W/m²
}

function generateNir(): Float32Array {
  return new Float32Array([
    jitter(0.22, 0.05),   // redEe W/m²
    jitter(0.06, 0.06),   // nirEeA
    jitter(0.04, 0.07),   // nirEeB
  ]);
}

function generatePlant(): Float32Array {
  const ppfd = jitterAbs(8.6, 0.3);
  return new Float32Array([
    jitter(1.62, 0.03),   // PAR
    jitter(0.78, 0.04),   // Eca
    jitter(0.66, 0.04),   // Ecb
    jitter(0.48, 0.05),   // Eb (400-500)
    jitter(0.62, 0.04),   // Ey (500-600)
    jitter(0.51, 0.05),   // Er (600-700)
    jitter(1.06, 0.03),   // Erb_ratio
    ppfd,                 // PPFD
    jitter(2.05, 0.04),   // PPFDb
    jitter(2.85, 0.04),   // PPFDy
    jitter(3.70, 0.04),   // PPFDr
    jitter(0.42, 0.05),   // PPFDfr
    jitter(43.0, 0.02),   // PPFDr_ratio
    jitter(33.1, 0.02),   // PPFDy_ratio
    jitter(23.9, 0.03),   // PPFDb_ratio
    jitter(7.95, 0.04),   // YPFD
  ]);
}

function generateTm30(): Float32Array {
  // 614 floats: 401 reference + 99 Eab + Rf + Rg + 16 chroma + 16 hue + 16 fidelity + 32 ces test pairs + 32 ces ref pairs.
  const out = new Float32Array(614);
  let idx = 0;
  // Reference spectrum (D50-ish 380..780nm at 1nm step → 401 samples)
  for (let i = 0; i < 401; i++) {
    const lambda = 380 + i;
    let v = 0;
    v += gaussian(lambda, 470, 60, 1.0);
    v += gaussian(lambda, 580, 80, 1.1);
    v += gaussian(lambda, 700, 100, 0.7);
    out[idx++] = Math.max(0, v + (Math.random() - 0.5) * 0.02);
  }
  // 99 Eab values (CIE colour difference samples, plausible 0.5..3 range)
  for (let i = 0; i < 99; i++) out[idx++] = jitter(1.5, 0.3);
  out[idx++] = jitterAbs(82, 2); // Rf
  out[idx++] = jitterAbs(98, 2); // Rg
  // 16 chromaShift (-5%..+5%)
  for (let i = 0; i < 16; i++) out[idx++] = jitterAbs(0, 2);
  // 16 hueShift (-3..+3 deg)
  for (let i = 0; i < 16; i++) out[idx++] = jitterAbs(0, 1.5);
  // 16 colorFidelity (75..95)
  for (let i = 0; i < 16; i++) out[idx++] = jitterAbs(85, 3);
  // 16 ces test pairs (a', b')
  for (let i = 0; i < 16; i++) {
    const theta = (i / 16) * 2 * Math.PI;
    out[idx++] = Math.cos(theta) * 30 + jitterAbs(0, 1); // a'
    out[idx++] = Math.sin(theta) * 30 + jitterAbs(0, 1); // b'
  }
  // 16 ces reference pairs (slightly larger radius, idealised)
  for (let i = 0; i < 16; i++) {
    const theta = (i / 16) * 2 * Math.PI;
    out[idx++] = Math.cos(theta) * 32;
    out[idx++] = Math.sin(theta) * 32;
  }
  if (idx !== 614) throw new Error(`tm30 generator wrote ${idx} floats, expected 614`);
  return out;
}

/* -------------------------------------------------------------------------- */
/* SpectrumFrame validData encoder                                            */
/* -------------------------------------------------------------------------- */

/** Pack a Float32Array into a Buffer (little-endian on all relevant platforms). */
function floatsToBuffer(floats: Float32Array): Buffer {
  return Buffer.from(floats.buffer, floats.byteOffset, floats.byteLength);
}

/** Encode a single SpectrumFrame validData blob matching PROTOCOL.md §4. */
export function buildSpectrumValidData(includeTm30: boolean, exposureUs: number): Buffer {
  const actual = generateActualSpectrum();
  // raw = round(actual * 10^N)
  const divisor = Math.pow(10, MOCK_SPECTRUM_COEFFICIENT);
  const raw = new Uint16Array(actual.length);
  for (let i = 0; i < actual.length; i++) {
    raw[i] = Math.max(0, Math.min(0xffff, Math.round(actual[i]! * divisor)));
  }

  const photometric = floatsToBuffer(generatePhotometric());
  const blueHazard = floatsToBuffer(generateBlueHazard());
  const nir = floatsToBuffer(generateNir());
  const plant = floatsToBuffer(generatePlant());
  const tm30 = includeTm30 ? floatsToBuffer(generateTm30()) : Buffer.alloc(0);

  const fixedLen = includeTm30 ? 2731 : 275;
  const rawBytes = raw.length * 2;
  const buf = Buffer.alloc(fixedLen + rawBytes);

  buf[0] = ExposureStatus.Normal;
  buf.writeUInt32LE(exposureUs >>> 0, 1);
  photometric.copy(buf, 5);
  blueHazard.copy(buf, 193);
  nir.copy(buf, 197);
  plant.copy(buf, 209);
  let coeffOffset: number;
  let rawOffset: number;
  if (includeTm30) {
    tm30.copy(buf, 273);
    coeffOffset = 2729;
    rawOffset = 2731;
  } else {
    coeffOffset = 273;
    rawOffset = 275;
  }
  buf.writeInt16LE(MOCK_SPECTRUM_COEFFICIENT, coeffOffset);
  // raw u16 spectrum, LE.
  for (let i = 0; i < raw.length; i++) {
    buf.writeUInt16LE(raw[i]!, rawOffset + 2 * i);
  }
  return buf;
}

/** Build a full spectrum response frame (header + validData + footer). */
export function buildSpectrumFrame(cmdType: number, exposureUs: number): Buffer {
  const includeTm30 =
    cmdType === protocol.CMD.CaptureSingleWithTm30 ||
    cmdType === protocol.CMD.StartStreamWithTm30;
  return buildResponseFrame(cmdType, buildSpectrumValidData(includeTm30, exposureUs));
}

/* -------------------------------------------------------------------------- */
/* Stateful mock device — wires write handlers to MockSerialPort              */
/* -------------------------------------------------------------------------- */

interface MockState {
  exposureMode: ExposureMode;
  exposureTimeUs: number;
  maxExposureTimeUs: number;
  cieMode: CieMode;
  workingMode: WorkingMode;
  sleeping: boolean;
}

const DEFAULT_STATE: MockState = {
  exposureMode: ExposureMode.Auto,
  exposureTimeUs: 2_500,
  maxExposureTimeUs: 1_000_000,
  cieMode: CieMode.Cie1931_2,
  workingMode: WorkingMode.Streaming,
  sleeping: false,
};

/** Minimal write/emit pair the MockSerialPort exposes. */
export interface MockPortLike {
  onWrite(listener: (chunk: Buffer) => void): void;
  emitData(chunk: Buffer): void;
}

/**
 * Register a single write listener that decodes incoming commands and pushes
 * synthetic responses back into the SDK. The listener is *additive*; the
 * caller is responsible for not calling this twice on the same port.
 *
 * Returns a `dispose()` that stops the streaming timer (if any) and detaches
 * nothing else (the SDK's own onClose handles teardown).
 */
export function attachMockHandlers(port: MockPortLike): { dispose(): void } {
  const state: MockState = { ...DEFAULT_STATE };
  let streaming: { cmdType: number; timer: NodeJS.Timeout } | null = null;

  const stopStreaming = (): void => {
    if (streaming) {
      clearInterval(streaming.timer);
      streaming = null;
    }
  };

  const startStreaming = (cmdType: number): void => {
    stopStreaming();
    const tick = (): void => {
      const frame = buildSpectrumFrame(cmdType, state.exposureTimeUs);
      port.emitData(frame);
    };
    // First frame immediately for snappy UX; thereafter ~5fps.
    queueMicrotask(tick);
    const timer = setInterval(tick, 200);
    streaming = { cmdType, timer };
  };

  port.onWrite((cmd: Buffer) => {
    // Defensive: any malformed cmd just gets ignored (silently dropped).
    if (cmd.length < protocol.FRAME_OVERHEAD) return;
    if (cmd[0] !== 0xcc || cmd[1] !== 0x01) return;
    const cmdType = cmd[5]!;
    const cmdDataStart = 6;
    const cmdDataEnd = cmd.length - 3; // exclude checksum + footer
    const cmdData = cmd.subarray(cmdDataStart, cmdDataEnd);

    const reply = (buf: Buffer): void => {
      // Defer to the next tick so the caller's promise has a chance to await.
      queueMicrotask(() => port.emitData(buf));
    };

    switch (cmdType) {
      case protocol.CMD.StopCapture:
        stopStreaming();
        return;

      case protocol.CMD.GetDeviceInfo:
        reply(buildResponseFrame(cmdType, Buffer.from(MOCK_SERIAL_NUMBER.padEnd(24, ' '), 'ascii')));
        return;

      case protocol.CMD.GetWavelengthRange: {
        const validData = Buffer.alloc(4);
        validData.writeUInt16LE(MOCK_WL_START, 0);
        validData.writeUInt16LE(MOCK_WL_END, 2);
        reply(buildResponseFrame(cmdType, validData));
        return;
      }

      case protocol.CMD.SetExposureMode:
        state.exposureMode = (cmdData[0] ?? 0) as ExposureMode;
        reply(buildStatusResponse(cmdType));
        return;

      case protocol.CMD.GetExposureMode:
        reply(buildResponseFrame(cmdType, Buffer.from([state.exposureMode])));
        return;

      case protocol.CMD.SetExposureTime:
        state.exposureTimeUs = cmdData.readUInt32LE(0);
        reply(buildStatusResponse(cmdType));
        return;

      case protocol.CMD.GetExposureTime: {
        const v = Buffer.alloc(4);
        v.writeUInt32LE(state.exposureTimeUs >>> 0, 0);
        reply(buildResponseFrame(cmdType, v));
        return;
      }

      case protocol.CMD.SetMaxExposureTime:
        state.maxExposureTimeUs = cmdData.readUInt32LE(0);
        reply(buildStatusResponse(cmdType));
        return;

      case protocol.CMD.GetMaxExposureTime: {
        const v = Buffer.alloc(4);
        v.writeUInt32LE(state.maxExposureTimeUs >>> 0, 0);
        reply(buildResponseFrame(cmdType, v));
        return;
      }

      case protocol.CMD.SetCieMode:
        state.cieMode = (cmdData[0] ?? 0) as CieMode;
        reply(buildStatusResponse(cmdType));
        return;

      case protocol.CMD.GetCieMode:
        reply(buildResponseFrame(cmdType, Buffer.from([state.cieMode])));
        return;

      case protocol.CMD.SetWorkingMode:
        state.workingMode = (cmdData[0] ?? 0) as WorkingMode;
        reply(buildStatusResponse(cmdType));
        return;

      case protocol.CMD.EnterExitSleep:
        state.sleeping = !state.sleeping;
        // No response per protocol.
        return;

      case protocol.CMD.CaptureSingleNoTm30:
      case protocol.CMD.CaptureSingleWithTm30:
        reply(buildSpectrumFrame(cmdType, state.exposureTimeUs));
        return;

      case protocol.CMD.StartStreamNoTm30:
      case protocol.CMD.StartStreamWithTm30:
        startStreaming(cmdType);
        return;

      case protocol.CMD.SendEfficiencyCurve:
        // Start packet (cmdData = 0x04) and chunk packets are both silent.
        return;

      case protocol.CMD.VerifyEfficiencyCurve:
      case protocol.CMD.ResetEfficiencyCurve:
        reply(buildStatusResponse(cmdType));
        return;

      default:
        // Unknown command → simulate 0x15 invalid-command status.
        reply(buildStatusResponse(cmdType, 0x15));
        return;
    }
  });

  return {
    dispose: (): void => {
      stopStreaming();
    },
  };
}
