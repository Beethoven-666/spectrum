/**
 * GET   — { mode, timeUs, maxTimeUs }
 * PATCH — partial update of any of those three fields.
 */

import { ExposureMode } from '@h1/sdk';

import { ensureAutoConnect, requireDevice } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface ExposureBody {
  mode?: 'auto' | 'manual';
  timeUs?: number;
  maxTimeUs?: number;
}

export async function GET(): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    const [mode, timeUs, maxTimeUs] = await Promise.all([
      device.getExposureMode(),
      device.getExposureTimeUs(),
      device.getMaxExposureTimeUs(),
    ]);
    return Response.json({
      mode: mode === ExposureMode.Auto ? 'auto' : 'manual',
      timeUs,
      maxTimeUs,
    });
  } catch (err) {
    return errorResponse(err);
  }
}

export async function PATCH(request: Request): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    const body = (await request.json()) as ExposureBody;
    if (body.mode !== undefined) {
      const m = body.mode === 'auto' ? ExposureMode.Auto : ExposureMode.Manual;
      await device.setExposureMode(m);
    }
    if (body.timeUs !== undefined) {
      if (!Number.isInteger(body.timeUs) || body.timeUs < 0) {
        return Response.json({ error: 'timeUs must be a non-negative integer (us)' }, { status: 400 });
      }
      await device.setExposureTimeUs(body.timeUs);
    }
    if (body.maxTimeUs !== undefined) {
      if (!Number.isInteger(body.maxTimeUs) || body.maxTimeUs < 0) {
        return Response.json({ error: 'maxTimeUs must be a non-negative integer (us)' }, { status: 400 });
      }
      await device.setMaxExposureTimeUs(body.maxTimeUs);
    }
    const [mode, timeUs, maxTimeUs] = await Promise.all([
      device.getExposureMode(),
      device.getExposureTimeUs(),
      device.getMaxExposureTimeUs(),
    ]);
    return Response.json({
      mode: mode === ExposureMode.Auto ? 'auto' : 'manual',
      timeUs,
      maxTimeUs,
    });
  } catch (err) {
    return errorResponse(err);
  }
}
