/**
 * Encoding tests — every command in PROTOCOL.md §9.1 must produce the exact
 * documented byte sequence.
 */

import { describe, expect, it } from 'vitest';

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
} from '../src/protocol.js';
import { CieMode, ExposureMode, WorkingMode } from '../src/types.js';

// Strip spaces and parse as a Buffer of hex bytes.
const hex = (s: string): Buffer => Buffer.from(s.replace(/\s+/g, ''), 'hex');

describe('PROTOCOL.md §9.1 — encoding test vectors', () => {
  it('StopCapture', () => {
    expect(buildStopCapture()).toEqual(hex('CC 01 09 00 00 04 DA 0D 0A'));
  });

  it('GetDeviceInfo', () => {
    expect(buildGetDeviceInfo()).toEqual(hex('CC 01 0A 00 00 08 18 F7 0D 0A'));
  });

  it('SetExposureMode(Manual)', () => {
    expect(buildSetExposureMode(ExposureMode.Manual)).toEqual(
      hex('CC 01 0A 00 00 0A 00 E1 0D 0A'),
    );
  });

  it('SetExposureMode(Auto)', () => {
    expect(buildSetExposureMode(ExposureMode.Auto)).toEqual(
      hex('CC 01 0A 00 00 0A 01 E2 0D 0A'),
    );
  });

  it('GetExposureMode', () => {
    expect(buildGetExposureMode()).toEqual(hex('CC 01 09 00 00 0B E1 0D 0A'));
  });

  it('SetExposureTime(100000)', () => {
    expect(buildSetExposureTime(100000)).toEqual(
      hex('CC 01 0D 00 00 0C A0 86 01 00 0D 0D 0A'),
    );
  });

  it('GetExposureTime', () => {
    expect(buildGetExposureTime()).toEqual(hex('CC 01 09 00 00 0D E3 0D 0A'));
  });

  it('GetWavelengthRange', () => {
    expect(buildGetWavelengthRange()).toEqual(hex('CC 01 09 00 00 0F E5 0D 0A'));
  });

  it('SetMaxExposureTime(5000000)', () => {
    expect(buildSetMaxExposureTime(5000000)).toEqual(
      hex('CC 01 0D 00 00 13 40 4B 4C 00 C4 0D 0A'),
    );
  });

  it('GetMaxExposureTime', () => {
    expect(buildGetMaxExposureTime()).toEqual(hex('CC 01 09 00 00 14 EA 0D 0A'));
  });

  it('SendEfficiencyCurveStart', () => {
    expect(buildSendEfficiencyCurveStart()).toEqual(hex('CC 01 0A 00 00 23 04 FE 0D 0A'));
  });

  it('VerifyEfficiencyCurve', () => {
    expect(buildVerifyEfficiencyCurve()).toEqual(hex('CC 01 09 00 00 27 FD 0D 0A'));
  });

  it('ResetEfficiencyCurve', () => {
    expect(buildResetEfficiencyCurve()).toEqual(hex('CC 01 09 00 00 25 FB 0D 0A'));
  });

  it('CaptureSingleNoTm30', () => {
    expect(buildCaptureSingleNoTm30()).toEqual(hex('CC 01 09 00 00 32 08 0D 0A'));
  });

  it('StartStreamNoTm30', () => {
    expect(buildStartStreamNoTm30()).toEqual(hex('CC 01 09 00 00 33 09 0D 0A'));
  });

  it('CaptureSingleWithTm30', () => {
    expect(buildCaptureSingleWithTm30()).toEqual(hex('CC 01 09 00 00 34 0A 0D 0A'));
  });

  it('StartStreamWithTm30', () => {
    expect(buildStartStreamWithTm30()).toEqual(hex('CC 01 09 00 00 35 0B 0D 0A'));
  });

  it('SetCieMode(Cie2015_2)', () => {
    expect(buildSetCieMode(CieMode.Cie2015_2)).toEqual(
      hex('CC 01 0A 00 00 36 02 0F 0D 0A'),
    );
  });

  it('GetCieMode', () => {
    expect(buildGetCieMode()).toEqual(hex('CC 01 09 00 00 37 0D 0D 0A'));
  });

  it('EnterExitSleep', () => {
    expect(buildEnterExitSleep()).toEqual(hex('CC 01 09 00 00 40 16 0D 0A'));
  });

  it('SetWorkingMode(Trigger)', () => {
    expect(buildSetWorkingMode(WorkingMode.Trigger)).toEqual(
      hex('CC 01 0A 00 00 41 01 19 0D 0A'),
    );
  });

  it('SetWorkingMode(Streaming)', () => {
    expect(buildSetWorkingMode(WorkingMode.Streaming)).toEqual(
      hex('CC 01 0A 00 00 41 00 18 0D 0A'),
    );
  });
});
