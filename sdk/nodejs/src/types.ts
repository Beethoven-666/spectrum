/**
 * Type definitions for the H1 spectrometer SDK.
 *
 * Field order in every interface mirrors the byte layout defined in
 * docs/PROTOCOL.md §4 and §5 so that decoding can be done with a simple
 * sequential read.
 */

/** Manual or automatic exposure (cmd 0x0A / 0x0B). */
export enum ExposureMode {
  Manual = 0x00,
  Auto = 0x01,
}

/** Streaming or trigger working mode (cmd 0x41). */
export enum WorkingMode {
  Streaming = 0x00,
  Trigger = 0x01,
}

/** CIE colour matching observer (cmd 0x36 / 0x37). */
export enum CieMode {
  Cie1931_2 = 0x00,
  Cie1964_10 = 0x01,
  Cie2015_2 = 0x02,
  Cie2015_10 = 0x03,
}

/** Exposure status byte at offset 0 of a SpectrumFrame. */
export enum ExposureStatus {
  Normal = 0x00,
  Over = 0x01,
  Under = 0x02,
}

/** Device-side status code returned for "set" style commands. */
export enum DeviceStatus {
  Success = 0x00,
  InvalidCommand = 0x15,
  UnsupportedOrOutOfRange = 0xff,
}

/** Wavelength range reported by the device (nm). */
export interface WavelengthRange {
  start: number;
  end: number;
}

/** Device serial number (24 ASCII characters). */
export interface DeviceInfo {
  serialNumber: string;
}

/** 47 photometric floats — order matches PROTOCOL.md §5.1. */
export interface PhotometricParams {
  X: number;
  Y: number;
  Z: number;
  x: number;
  y: number;
  uk: number;
  vk: number;
  u_prime: number;
  v_prime: number;
  CCT: number;
  Nit: number;
  r_ratio: number;
  g_ratio: number;
  b_ratio: number;
  DUV: number;
  Ra: number;
  R1: number;
  R2: number;
  R3: number;
  R4: number;
  R5: number;
  R6: number;
  R7: number;
  R8: number;
  R9: number;
  R10: number;
  R11: number;
  R12: number;
  R13: number;
  R14: number;
  R15: number;
  Lp: number;
  HW: number;
  Ld: number;
  purity: number;
  SP: number;
  SDCM_k: number;
  k: number;
  lux: number;
  Ee: number;
  fc: number;
  CQS: number;
  GAI_EES: number;
  GAI_BB_8: number;
  GAI_BB_15: number;
  EML: number;
  M_EDI: number;
}

/** Single-float blue hazard parameter. */
export interface BlueHazardParams {
  Eb: number;
}

/** Three NIR floats (W/m²). */
export interface NirParams {
  redEe: number;
  nirEeA: number;
  nirEeB: number;
}

/** 16 plant-growth related parameters — order matches PROTOCOL.md §5.4. */
export interface PlantParams {
  PAR: number;
  Eca: number;
  Ecb: number;
  Eb: number;
  Ey: number;
  Er: number;
  Erb_ratio: number;
  PPFD: number;
  PPFDb: number;
  PPFDy: number;
  PPFDr: number;
  PPFDfr: number;
  PPFDr_ratio: number;
  PPFDy_ratio: number;
  PPFDb_ratio: number;
  YPFD: number;
}

/**
 * TM-30 colour rendering metrics — 614 floats in total.
 * Lengths fixed by PROTOCOL.md §5.5.
 */
export interface Tm30Params {
  /** 401 reference spectrum samples. */
  referenceSpectrum: number[];
  /** 99 Eab values. */
  Eab: number[];
  Rf: number;
  Rg: number;
  /** 16 chromaShift values. */
  chromaShift: number[];
  /** 16 hueShift values. */
  hueShift: number[];
  /** 16 colorFidelity values. */
  colorFidelity: number[];
  /** 16 pairs of (a', b') test values. */
  cesAbTest: number[][];
  /** 16 pairs of (a', b') reference values. */
  cesAbReference: number[][];
}

/**
 * A single spectrometer measurement.
 *
 * `tm30` is undefined when the frame came from cmdType 0x32/0x33 (no TM30).
 */
export interface SpectrumFrame {
  exposureStatus: ExposureStatus;
  exposureTimeUs: number;
  photometric: PhotometricParams;
  blueHazard: BlueHazardParams;
  nir: NirParams;
  plant: PlantParams;
  tm30?: Tm30Params;
  /** Power-of-ten divisor: actual = raw / 10^spectrumCoefficient. */
  spectrumCoefficient: number;
  /** M raw u16 readings (M = wavelengthEnd - wavelengthStart + 1). */
  rawSpectrum: Uint16Array;
  /** Convenience: rawSpectrum decoded to floats using spectrumCoefficient. */
  actualSpectrum: Float32Array;
}

/** Options accepted by the Device constructor. */
export interface DeviceOptions {
  /** Serial baud rate. Defaults to 115_200. */
  baudRate?: number;
  /** Default per-request timeout (ms). Defaults to 1000. */
  defaultTimeoutMs?: number;
}
