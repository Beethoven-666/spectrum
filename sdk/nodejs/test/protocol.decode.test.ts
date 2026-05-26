/**
 * Decoding tests — every response shown in PROTOCOL.md §9.2 must round-trip to
 * the documented field values.
 */

import { describe, expect, it } from 'vitest';

import { DeviceError, ProtocolError } from '../src/errors.js';
import {
  CMD,
  checkSetStatus,
  decodeCieMode,
  decodeDeviceInfo,
  decodeExposureMode,
  decodeExposureTimeUs,
  decodeWavelengthRange,
  parseResponse,
} from '../src/protocol.js';
import { CieMode, ExposureMode } from '../src/types.js';

const hex = (s: string): Buffer => Buffer.from(s.replace(/\s+/g, ''), 'hex');

describe('PROTOCOL.md §9.2 — decoding test vectors', () => {
  it('DeviceInfo response — SN ASCII', () => {
    const frame = hex(
      'CC 81 21 00 00 08 ' +
        '48 31 31 42 36 56 31 30 35 33 34 43 46 50 44 2D 31 30 30 2D 30 30 30 32 ' +
        'B5 0D 0A',
    );
    const { dataType, validData } = parseResponse(frame, CMD.GetDeviceInfo);
    expect(dataType).toBe(CMD.GetDeviceInfo);
    expect(decodeDeviceInfo(validData)).toEqual({
      serialNumber: 'H11B6V10534CFPD-100-0002',
    });
  });

  it('WavelengthRange response — 340..1050 nm', () => {
    const frame = hex('CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A');
    const { validData } = parseResponse(frame, CMD.GetWavelengthRange);
    expect(decodeWavelengthRange(validData)).toEqual({ start: 340, end: 1050 });
  });

  it('GetExposureTime response — 100000 us', () => {
    const frame = hex('CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A');
    const { validData } = parseResponse(frame, CMD.GetExposureTime);
    expect(decodeExposureTimeUs(validData)).toBe(100000);
  });

  it('GetMaxExposureTime response — 1000000 us', () => {
    const frame = hex('CC 81 0D 00 00 14 40 42 0F 00 FF 0D 0A');
    const { validData } = parseResponse(frame, CMD.GetMaxExposureTime);
    expect(decodeExposureTimeUs(validData)).toBe(1000000);
  });

  it('GetCieMode response — CIE2015 2°', () => {
    const frame = hex('CC 81 0A 00 00 37 02 90 0D 0A');
    const { validData } = parseResponse(frame, CMD.GetCieMode);
    expect(decodeCieMode(validData)).toBe(CieMode.Cie2015_2);
  });

  it('GetExposureMode response — manual', () => {
    const frame = hex('CC 81 0A 00 00 0B 00 62 0D 0A');
    const { validData } = parseResponse(frame, CMD.GetExposureMode);
    expect(decodeExposureMode(validData)).toBe(ExposureMode.Manual);
  });

  it('GetExposureMode response — auto', () => {
    const frame = hex('CC 81 0A 00 00 0B 01 63 0D 0A');
    const { validData } = parseResponse(frame, CMD.GetExposureMode);
    expect(decodeExposureMode(validData)).toBe(ExposureMode.Auto);
  });

  it('Set success response (0x0A) — does not throw', () => {
    const frame = hex('CC 81 0A 00 00 0A 00 61 0D 0A');
    const { validData } = parseResponse(frame, CMD.SetExposureMode);
    expect(() => checkSetStatus(validData, CMD.SetExposureMode)).not.toThrow();
  });

  it('Set failure 0x15 → DeviceError(code=0x15)', () => {
    const frame = hex('CC 81 0A 00 00 0A 15 76 0D 0A');
    const { validData } = parseResponse(frame, CMD.SetExposureMode);
    try {
      checkSetStatus(validData, CMD.SetExposureMode);
      throw new Error('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(DeviceError);
      const de = err as DeviceError;
      expect(de.code).toBe(0x15);
      expect(de.cmdType).toBe(CMD.SetExposureMode);
    }
  });

  it('Set failure 0xFF → DeviceError(code=0xFF)', () => {
    const frame = hex('CC 81 0A 00 00 0A FF 60 0D 0A');
    const { validData } = parseResponse(frame, CMD.SetExposureMode);
    try {
      checkSetStatus(validData, CMD.SetExposureMode);
      throw new Error('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(DeviceError);
      expect((err as DeviceError).code).toBe(0xff);
    }
  });
});

describe('PROTOCOL.md §9.3 — checksum / frame integrity', () => {
  const goodWavelength = hex('CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A');

  it('bad checksum → ProtocolError', () => {
    const bad = Buffer.from(goodWavelength);
    bad[10] = (bad[10]! + 1) & 0xff;
    expect(() => parseResponse(bad, CMD.GetWavelengthRange)).toThrow(ProtocolError);
  });

  it('bad header → ProtocolError', () => {
    const bad = Buffer.from(goodWavelength);
    bad[0] = 0xee;
    expect(() => parseResponse(bad, CMD.GetWavelengthRange)).toThrow(ProtocolError);
  });

  it('bad footer → ProtocolError', () => {
    const bad = Buffer.from(goodWavelength);
    bad[bad.length - 1] = 0x00;
    expect(() => parseResponse(bad, CMD.GetWavelengthRange)).toThrow(ProtocolError);
  });

  it('totalLen mismatch → ProtocolError', () => {
    const bad = Buffer.from(goodWavelength);
    bad[2] = 0xff; // claim a much larger total length
    expect(() => parseResponse(bad, CMD.GetWavelengthRange)).toThrow(ProtocolError);
  });

  it('truncated frame → ProtocolError', () => {
    const truncated = goodWavelength.subarray(0, 5);
    expect(() => parseResponse(truncated, CMD.GetWavelengthRange)).toThrow(ProtocolError);
  });

  it('dataType mismatch → ProtocolError', () => {
    expect(() => parseResponse(goodWavelength, CMD.GetExposureTime)).toThrow(ProtocolError);
  });
});
