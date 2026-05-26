/**
 * JSON-friendly representations of SDK frame data.
 *
 * The raw SDK returns `Uint16Array` / `Float32Array` views, which JSON.stringify
 * would turn into objects with numeric keys. We convert them to plain arrays
 * before sending over the wire.
 */

import type { SpectrumFrame } from '@h1/sdk';

export interface SerializedSpectrumFrame {
  exposureStatus: number;
  exposureTimeUs: number;
  photometric: SpectrumFrame['photometric'];
  blueHazard: SpectrumFrame['blueHazard'];
  nir: SpectrumFrame['nir'];
  plant: SpectrumFrame['plant'];
  tm30: SpectrumFrame['tm30'] | undefined;
  spectrumCoefficient: number;
  wavelengthStart: number;
  /** Plain `number[]` of length M. */
  rawSpectrum: number[];
  actualSpectrum: number[];
  /** Convenience array of length M; `wavelengths[i] = wavelengthStart + i`. */
  wavelengths: number[];
}

export function serializeFrame(
  frame: SpectrumFrame,
  wavelengthStart: number,
): SerializedSpectrumFrame {
  const rawSpectrum = Array.from(frame.rawSpectrum);
  const actualSpectrum = Array.from(frame.actualSpectrum);
  const wavelengths = new Array<number>(rawSpectrum.length);
  for (let i = 0; i < rawSpectrum.length; i++) wavelengths[i] = wavelengthStart + i;
  return {
    exposureStatus: frame.exposureStatus,
    exposureTimeUs: frame.exposureTimeUs,
    photometric: frame.photometric,
    blueHazard: frame.blueHazard,
    nir: frame.nir,
    plant: frame.plant,
    tm30: frame.tm30,
    spectrumCoefficient: frame.spectrumCoefficient,
    wavelengthStart,
    rawSpectrum,
    actualSpectrum,
    wavelengths,
  };
}
