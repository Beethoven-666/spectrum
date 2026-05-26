/**
 * End-to-end Device tests using MockSerialPort.
 *
 * Each test installs canned responses for the commands the SDK will issue and
 * exercises the public API. Streaming is covered by feeding a sequence of
 * frames synchronously after `startStreaming` returns.
 */

import { describe, expect, it } from 'vitest';

import { Device, type SerialPortLike } from '../src/device.js';
import { DeviceError, TimeoutError } from '../src/errors.js';
import { MockSerialPort } from '../src/mock.js';
import {
  buildCaptureSingleNoTm30,
  buildGetCieMode,
  buildGetDeviceInfo,
  buildGetExposureTime,
  buildGetWavelengthRange,
  buildResetEfficiencyCurve,
  buildSetExposureMode,
  buildStartStreamNoTm30,
  buildStopCapture,
  buildVerifyEfficiencyCurve,
  CMD,
} from '../src/protocol.js';
import { CieMode, ExposureMode, ExposureStatus, type SpectrumFrame } from '../src/types.js';

const hex = (s: string): Buffer => Buffer.from(s.replace(/\s+/g, ''), 'hex');

function makeDevice(port: MockSerialPort): Device {
  return new Device(port as unknown as SerialPortLike, { defaultTimeoutMs: 500 });
}

// -----------------------------------------------------------------------------
// Synthetic spectrum frame helpers (copy of test/spectrum.test.ts logic, then
// wrapped in a complete response frame).
// -----------------------------------------------------------------------------

import { checksum, FOOTER_0, FOOTER_1, FRAME_OVERHEAD, HEADER_RESP_0, HEADER_RESP_1, writeUInt24LE } from '../src/protocol.js';

function wrapResponse(cmdType: number, validData: Buffer): Buffer {
  const totalLen = FRAME_OVERHEAD + validData.length;
  const buf = Buffer.alloc(totalLen);
  buf[0] = HEADER_RESP_0;
  buf[1] = HEADER_RESP_1;
  writeUInt24LE(buf, totalLen, 2);
  buf[5] = cmdType;
  validData.copy(buf, 6);
  const checksumOffset = 6 + validData.length;
  buf[checksumOffset] = checksum(buf, 0, checksumOffset);
  buf[checksumOffset + 1] = FOOTER_0;
  buf[checksumOffset + 2] = FOOTER_1;
  return buf;
}

function synthSpectrumValidData(opts: { tm30: boolean; m?: number; coefficient?: number }): Buffer {
  const m = opts.m ?? 8;
  const fixed = opts.tm30 ? 2731 : 275;
  const buf = Buffer.alloc(fixed + 2 * m);
  buf[0] = ExposureStatus.Normal;
  buf.writeUInt32LE(1000, 1);
  // All other floats stay zero — enough to exercise layout.
  if (opts.tm30) {
    buf.writeInt16LE(opts.coefficient ?? 0, 2729);
    for (let i = 0; i < m; i++) buf.writeUInt16LE(i + 1, 2731 + i * 2);
  } else {
    buf.writeInt16LE(opts.coefficient ?? 0, 273);
    for (let i = 0; i < m; i++) buf.writeUInt16LE(i + 1, 275 + i * 2);
  }
  return buf;
}

// -----------------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------------

describe('Device — simple commands round-trip', () => {
  it('getDeviceInfo', async () => {
    const port = new MockSerialPort();
    port.respondTo(
      buildGetDeviceInfo(),
      hex(
        'CC 81 21 00 00 08 ' +
          '48 31 31 42 36 56 31 30 35 33 34 43 46 50 44 2D 31 30 30 2D 30 30 30 32 ' +
          'B5 0D 0A',
      ),
    );
    const dev = makeDevice(port);
    try {
      const info = await dev.getDeviceInfo();
      expect(info.serialNumber).toBe('H11B6V10534CFPD-100-0002');
    } finally {
      await dev.close();
    }
  });

  it('getWavelengthRange', async () => {
    const port = new MockSerialPort();
    port.respondTo(buildGetWavelengthRange(), hex('CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A'));
    const dev = makeDevice(port);
    try {
      const r = await dev.getWavelengthRange();
      expect(r).toEqual({ start: 340, end: 1050 });
    } finally {
      await dev.close();
    }
  });

  it('getExposureTimeUs', async () => {
    const port = new MockSerialPort();
    port.respondTo(buildGetExposureTime(), hex('CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A'));
    const dev = makeDevice(port);
    try {
      expect(await dev.getExposureTimeUs()).toBe(100000);
    } finally {
      await dev.close();
    }
  });

  it('getCieMode', async () => {
    const port = new MockSerialPort();
    port.respondTo(buildGetCieMode(), hex('CC 81 0A 00 00 37 02 90 0D 0A'));
    const dev = makeDevice(port);
    try {
      expect(await dev.getCieMode()).toBe(CieMode.Cie2015_2);
    } finally {
      await dev.close();
    }
  });

  it('setExposureMode success', async () => {
    const port = new MockSerialPort();
    port.respondTo(buildSetExposureMode(ExposureMode.Manual), hex('CC 81 0A 00 00 0A 00 61 0D 0A'));
    const dev = makeDevice(port);
    try {
      await expect(dev.setExposureMode(ExposureMode.Manual)).resolves.toBeUndefined();
    } finally {
      await dev.close();
    }
  });

  it('setExposureMode device error 0x15 → DeviceError', async () => {
    const port = new MockSerialPort();
    port.respondTo(buildSetExposureMode(ExposureMode.Manual), hex('CC 81 0A 00 00 0A 15 76 0D 0A'));
    const dev = makeDevice(port);
    try {
      await expect(dev.setExposureMode(ExposureMode.Manual)).rejects.toMatchObject({
        name: 'DeviceError',
        code: 0x15,
        cmdType: CMD.SetExposureMode,
      });
    } finally {
      await dev.close();
    }
  });

  it('setExposureMode device error 0xFF → DeviceError', async () => {
    const port = new MockSerialPort();
    port.respondTo(buildSetExposureMode(ExposureMode.Auto), hex('CC 81 0A 00 00 0A FF 60 0D 0A'));
    const dev = makeDevice(port);
    try {
      await expect(dev.setExposureMode(ExposureMode.Auto)).rejects.toBeInstanceOf(DeviceError);
    } finally {
      await dev.close();
    }
  });

  it('resetEfficiencyCurve success', async () => {
    const port = new MockSerialPort();
    port.respondTo(buildResetEfficiencyCurve(), hex('CC 81 0A 00 00 25 00 7C 0D 0A'));
    const dev = makeDevice(port);
    try {
      await dev.resetEfficiencyCurve();
    } finally {
      await dev.close();
    }
  });
});

describe('Device — timeout handling', () => {
  it('no response → TimeoutError', async () => {
    const port = new MockSerialPort();
    // No respondTo() — port will swallow writes silently.
    const dev = new Device(port as unknown as SerialPortLike, { defaultTimeoutMs: 80 });
    try {
      await expect(dev.getExposureTimeUs()).rejects.toBeInstanceOf(TimeoutError);
    } finally {
      await dev.close();
    }
  });
});

describe('Device — captureSingle', () => {
  it('returns a decoded SpectrumFrame (no TM30)', async () => {
    const port = new MockSerialPort();
    const valid = synthSpectrumValidData({ tm30: false, m: 4, coefficient: 2 });
    port.respondTo(buildCaptureSingleNoTm30(), wrapResponse(CMD.CaptureSingleNoTm30, valid));
    const dev = makeDevice(port);
    try {
      const f = await dev.captureSingle(false);
      expect(f.exposureStatus).toBe(ExposureStatus.Normal);
      expect(f.exposureTimeUs).toBe(1000);
      expect(f.rawSpectrum.length).toBe(4);
      expect(Array.from(f.rawSpectrum)).toEqual([1, 2, 3, 4]);
      expect(f.spectrumCoefficient).toBe(2);
      expect(f.actualSpectrum[0]).toBeCloseTo(0.01);
      expect(f.tm30).toBeUndefined();
    } finally {
      await dev.close();
    }
  });

  it('returns a TM30 SpectrumFrame when includeTm30 = true', async () => {
    const port = new MockSerialPort();
    const valid = synthSpectrumValidData({ tm30: true, m: 4, coefficient: 0 });
    port.respondTo(
      Buffer.from([0xcc, 0x01, 0x09, 0x00, 0x00, 0x34, 0x0a, 0x0d, 0x0a]),
      wrapResponse(CMD.CaptureSingleWithTm30, valid),
    );
    const dev = makeDevice(port);
    try {
      const f = await dev.captureSingle(true);
      expect(f.tm30).toBeDefined();
      expect(f.tm30!.referenceSpectrum.length).toBe(401);
      expect(f.tm30!.cesAbTest.length).toBe(16);
      expect(f.rawSpectrum[0]).toBe(1);
    } finally {
      await dev.close();
    }
  });
});

describe('Device — streaming', () => {
  it('emits N frames, then stops cleanly', async () => {
    const port = new MockSerialPort();
    const dev = makeDevice(port);
    const valid = synthSpectrumValidData({ tm30: false, m: 6 });
    const frameBytes = wrapResponse(CMD.StartStreamNoTm30, valid);

    let acceptStop = false;

    // When the SDK writes the StartStream command, push 3 frames through.
    port.onWrite((chunk) => {
      if (chunk.equals(buildStartStreamNoTm30())) {
        queueMicrotask(() => {
          for (let i = 0; i < 3; i++) port.emitData(frameBytes);
        });
      } else if (chunk.equals(buildStopCapture())) {
        acceptStop = true;
      }
    });

    const received: SpectrumFrame[] = [];
    const done = new Promise<void>((resolve) => {
      dev.on('frame', (f: SpectrumFrame) => {
        received.push(f);
        if (received.length === 3) resolve();
      });
    });

    await dev.startStreaming(false);
    expect(dev.isStreaming()).toBe(true);
    await done;
    await dev.stopStreaming();
    expect(dev.isStreaming()).toBe(false);
    expect(acceptStop).toBe(true);
    expect(received).toHaveLength(3);
    for (const f of received) {
      expect(f.rawSpectrum.length).toBe(6);
    }
    await dev.close();
  });

  it('trailing frames after stop are dropped', async () => {
    const port = new MockSerialPort();
    const dev = makeDevice(port);
    const valid = synthSpectrumValidData({ tm30: false, m: 3 });
    const frameBytes = wrapResponse(CMD.StartStreamNoTm30, valid);

    port.onWrite((chunk) => {
      if (chunk.equals(buildStartStreamNoTm30())) {
        queueMicrotask(() => port.emitData(frameBytes));
      }
      if (chunk.equals(buildStopCapture())) {
        // Simulate the device sending one extra buffered frame after stop.
        queueMicrotask(() => port.emitData(frameBytes));
      }
    });

    let frames = 0;
    dev.on('frame', () => frames++);
    await dev.startStreaming(false);
    await new Promise((r) => setTimeout(r, 20));
    await dev.stopStreaming();
    // We expect exactly 1 frame (the one before stop), the trailing one is dropped.
    expect(frames).toBe(1);
    await dev.close();
  });
});

describe('Device — handles fragmented and merged frames', () => {
  it('splits a single chunk that contains two back-to-back response frames', async () => {
    // Drive the framing logic in drain() directly by sending two response
    // frames glued together. The first satisfies the in-flight request; the
    // second is then dispatched against the next request.
    const port = new MockSerialPort();
    const dev = makeDevice(port);

    // Both replies arrive in a single chunk in response to GetExposureTime.
    port.onWrite((chunk) => {
      if (chunk.equals(buildGetExposureTime())) {
        const glued = Buffer.concat([
          hex('CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A'),
          hex('CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A'),
        ]);
        queueMicrotask(() => port.emitData(glued));
      }
    });

    // Catch the stray-frame error so it doesn't reach the process listener.
    const stray: Error[] = [];
    dev.on('error', (e) => stray.push(e));

    try {
      const us = await dev.getExposureTimeUs();
      expect(us).toBe(100000);
      // The second frame was buffered but had no in-flight request — the device
      // emits an 'error' event for it. We expect exactly one such error.
      await new Promise((r) => setTimeout(r, 10));
      expect(stray).toHaveLength(1);
      expect(stray[0]).toBeInstanceOf(Error);
    } finally {
      await dev.close();
    }
  });

  it('reassembles a response delivered byte-by-byte', async () => {
    const port = new MockSerialPort();
    const dev = makeDevice(port);
    const reply = hex('CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A');
    port.respondTo(buildGetExposureTime(), () => {
      queueMicrotask(() => {
        for (const b of reply) port.emitData(Buffer.from([b]));
      });
      return undefined; // suppress automatic single-shot reply
    });
    try {
      const us = await dev.getExposureTimeUs();
      expect(us).toBe(100000);
    } finally {
      await dev.close();
    }
  });
});

describe('Device — efficiency curve upload', () => {
  it('sends start packet, chunks, then verify', async () => {
    const port = new MockSerialPort();
    const dev = makeDevice(port);
    const writes: Buffer[] = [];
    port.onWrite((chunk) => writes.push(Buffer.from(chunk)));
    port.respondTo(buildVerifyEfficiencyCurve(), hex('CC 81 0A 00 00 27 00 7E 0D 0A'));

    // 500 ratios of 1.5 → needs 3 packets (247, 247, 6 floats).
    const ratios = new Float32Array(500);
    ratios.fill(1.5);
    await dev.uploadEfficiencyCurve(ratios);

    // Writes: start packet + 3 data chunks + verify.
    expect(writes.length).toBe(5);
    expect(writes[0]).toEqual(hex('CC 01 0A 00 00 23 04 FE 0D 0A')); // start
    // The 4th write (index 3) is the trailing tiny packet with 6 floats.
    const trailingExpectedDataLen = 6 * 4;
    expect(writes[3]!.length).toBe(9 + trailingExpectedDataLen);
    expect(writes[4]).toEqual(hex('CC 01 09 00 00 27 FD 0D 0A')); // verify
    await dev.close();
  });
});
