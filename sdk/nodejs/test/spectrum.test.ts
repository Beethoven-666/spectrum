/**
 * SpectrumFrame layout tests (PROTOCOL.md §9.4).
 *
 * Build a synthetic validData blob with known field values at every offset
 * and check that the decoder pulls each field from the right place.
 */

import { describe, expect, it } from 'vitest';

import { decodeSpectrumFrame } from '../src/protocol.js';
import { ExposureStatus } from '../src/types.js';

const M = 711;

/** Construct a "no TM30" spectrum frame's validData portion. */
function synthFrameNoTm30(): Buffer {
  const buf = Buffer.alloc(275 + 2 * M);
  buf[0] = ExposureStatus.Normal;
  buf.writeUInt32LE(2500, 1); // 2500 us
  // photometric: 47 floats, set X=1, Y=2, ..., R15 distinguishable
  // We pick a deterministic sequence: photometric[i] = (i+1) * 0.5
  for (let i = 0; i < 47; i++) {
    buf.writeFloatLE((i + 1) * 0.5, 5 + i * 4);
  }
  // blueHazard: 1 float at 193
  buf.writeFloatLE(123.5, 193);
  // nir: 3 floats at 197
  buf.writeFloatLE(10.1, 197);
  buf.writeFloatLE(20.2, 201);
  buf.writeFloatLE(30.3, 205);
  // plant: 16 floats at 209 — plant[i] = -(i+1)
  for (let i = 0; i < 16; i++) {
    buf.writeFloatLE(-(i + 1), 209 + i * 4);
  }
  // spectrumCoefficient: i16 at 273 = 2 (so divide raw by 100)
  buf.writeInt16LE(2, 273);
  // rawSpectrum: u16 little-endian, increasing 0,1,2,..,M-1
  for (let i = 0; i < M; i++) {
    buf.writeUInt16LE(i, 275 + i * 2);
  }
  return buf;
}

/** Construct a "with TM30" spectrum frame's validData portion. */
function synthFrameWithTm30(): Buffer {
  const buf = Buffer.alloc(2731 + 2 * M);
  buf[0] = ExposureStatus.Over;
  buf.writeUInt32LE(7777, 1);
  for (let i = 0; i < 47; i++) {
    buf.writeFloatLE(i + 1, 5 + i * 4);
  }
  buf.writeFloatLE(1.25, 193);
  buf.writeFloatLE(2.5, 197);
  buf.writeFloatLE(3.75, 201);
  buf.writeFloatLE(5.0, 205);
  for (let i = 0; i < 16; i++) {
    buf.writeFloatLE(100 + i, 209 + i * 4);
  }
  // TM-30 region: 614 floats starting at offset 273
  // Use a recognisable pattern: tm30_float[i] = i * 0.25
  for (let i = 0; i < 614; i++) {
    buf.writeFloatLE(i * 0.25, 273 + i * 4);
  }
  buf.writeInt16LE(-1, 2729); // coefficient = -1 → divisor = 0.1 → actual = raw * 10
  for (let i = 0; i < M; i++) {
    buf.writeUInt16LE(M - 1 - i, 2731 + i * 2);
  }
  return buf;
}

describe('SpectrumFrame decode — no TM30', () => {
  const frame = decodeSpectrumFrame(synthFrameNoTm30(), false);

  it('reads scalar header', () => {
    expect(frame.exposureStatus).toBe(ExposureStatus.Normal);
    expect(frame.exposureTimeUs).toBe(2500);
  });

  it('reads photometric fields in order', () => {
    expect(frame.photometric.X).toBeCloseTo(0.5);
    expect(frame.photometric.Y).toBeCloseTo(1.0);
    expect(frame.photometric.Z).toBeCloseTo(1.5);
    expect(frame.photometric.x).toBeCloseTo(2.0);
    expect(frame.photometric.y).toBeCloseTo(2.5);
    expect(frame.photometric.Ra).toBeCloseTo(8.0); // index 15 → (15+1)*0.5
    expect(frame.photometric.R15).toBeCloseTo(15.5); // index 30
    expect(frame.photometric.Lp).toBeCloseTo(16.0); // index 31
    expect(frame.photometric.M_EDI).toBeCloseTo(23.5); // index 46
  });

  it('reads blueHazard', () => {
    expect(frame.blueHazard.Eb).toBeCloseTo(123.5);
  });

  it('reads NIR triplet', () => {
    expect(frame.nir).toEqual({
      redEe: expect.closeTo(10.1, 3) as unknown as number,
      nirEeA: expect.closeTo(20.2, 3) as unknown as number,
      nirEeB: expect.closeTo(30.3, 3) as unknown as number,
    });
  });

  it('reads plant fields in order', () => {
    expect(frame.plant.PAR).toBeCloseTo(-1);
    expect(frame.plant.Eca).toBeCloseTo(-2);
    expect(frame.plant.YPFD).toBeCloseTo(-16);
  });

  it('tm30 is undefined for the no-TM30 layout', () => {
    expect(frame.tm30).toBeUndefined();
  });

  it('rawSpectrum is decoded as M little-endian u16s', () => {
    expect(frame.rawSpectrum.length).toBe(M);
    expect(frame.rawSpectrum[0]).toBe(0);
    expect(frame.rawSpectrum[1]).toBe(1);
    expect(frame.rawSpectrum[M - 1]).toBe(M - 1);
  });

  it('spectrumCoefficient and actualSpectrum derived correctly', () => {
    expect(frame.spectrumCoefficient).toBe(2);
    // actual = raw / 10^2 = raw / 100
    expect(frame.actualSpectrum[0]).toBeCloseTo(0);
    expect(frame.actualSpectrum[100]).toBeCloseTo(1.0);
    expect(frame.actualSpectrum[200]).toBeCloseTo(2.0);
  });
});

describe('SpectrumFrame decode — with TM30', () => {
  const frame = decodeSpectrumFrame(synthFrameWithTm30(), true);

  it('header values', () => {
    expect(frame.exposureStatus).toBe(ExposureStatus.Over);
    expect(frame.exposureTimeUs).toBe(7777);
  });

  it('photometric still anchored at offset 5', () => {
    expect(frame.photometric.X).toBeCloseTo(1.0);
    expect(frame.photometric.M_EDI).toBeCloseTo(47.0);
  });

  it('plant region preserved', () => {
    expect(frame.plant.PAR).toBeCloseTo(100);
    expect(frame.plant.YPFD).toBeCloseTo(115);
  });

  it('tm30 region decoded', () => {
    const tm30 = frame.tm30;
    expect(tm30).toBeDefined();
    if (!tm30) return;
    expect(tm30.referenceSpectrum.length).toBe(401);
    expect(tm30.Eab.length).toBe(99);
    expect(tm30.chromaShift.length).toBe(16);
    expect(tm30.hueShift.length).toBe(16);
    expect(tm30.colorFidelity.length).toBe(16);
    expect(tm30.cesAbTest.length).toBe(16);
    expect(tm30.cesAbReference.length).toBe(16);
    for (const pair of tm30.cesAbTest) {
      expect(pair.length).toBe(2);
    }
    for (const pair of tm30.cesAbReference) {
      expect(pair.length).toBe(2);
    }
    // First reference sample = 0 * 0.25 = 0; last = 400 * 0.25 = 100
    expect(tm30.referenceSpectrum[0]).toBeCloseTo(0);
    expect(tm30.referenceSpectrum[400]).toBeCloseTo(100);
    // First Eab = 401 * 0.25 = 100.25
    expect(tm30.Eab[0]).toBeCloseTo(100.25);
    // Rf at index 500, Rg at index 501
    expect(tm30.Rf).toBeCloseTo(125.0);
    expect(tm30.Rg).toBeCloseTo(125.25);
    // chromaShift[0] = 502*0.25 = 125.5
    expect(tm30.chromaShift[0]).toBeCloseTo(125.5);
    // hueShift[0] = 518*0.25 = 129.5
    expect(tm30.hueShift[0]).toBeCloseTo(129.5);
    // colorFidelity[0] = 534*0.25 = 133.5
    expect(tm30.colorFidelity[0]).toBeCloseTo(133.5);
    // cesAbTest[0] = (550*0.25, 551*0.25) = (137.5, 137.75)
    expect(tm30.cesAbTest[0]![0]).toBeCloseTo(137.5);
    expect(tm30.cesAbTest[0]![1]).toBeCloseTo(137.75);
    // cesAbReference[0] = (582*0.25, 583*0.25) = (145.5, 145.75)
    expect(tm30.cesAbReference[0]![0]).toBeCloseTo(145.5);
    expect(tm30.cesAbReference[0]![1]).toBeCloseTo(145.75);
  });

  it('spectrumCoefficient negative → actual is raw * 10', () => {
    expect(frame.spectrumCoefficient).toBe(-1);
    expect(frame.rawSpectrum[0]).toBe(M - 1);
    expect(frame.actualSpectrum[0]).toBeCloseTo((M - 1) * 10);
  });
});

describe('SpectrumFrame decode — error cases', () => {
  it('short buffer throws ProtocolError', () => {
    expect(() => decodeSpectrumFrame(Buffer.alloc(10), false)).toThrow();
  });
  it('odd-byte tail throws ProtocolError', () => {
    const buf = Buffer.alloc(275 + 1); // 1 trailing byte (odd)
    expect(() => decodeSpectrumFrame(buf, false)).toThrow();
  });
});
