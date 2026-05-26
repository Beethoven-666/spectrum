/**
 * POST /api/device/efficiency-curve — upload the start packet + chunks + verify.
 * Body: { ratios: number[] }
 */

import { ensureAutoConnect, requireDevice } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface Body {
  ratios: number[];
}

export async function POST(request: Request): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    const body = (await request.json()) as Body;
    if (!Array.isArray(body.ratios) || body.ratios.length === 0) {
      return Response.json({ error: 'ratios must be a non-empty array of numbers' }, { status: 400 });
    }
    for (const v of body.ratios) {
      if (typeof v !== 'number' || !Number.isFinite(v)) {
        return Response.json({ error: 'ratios must contain only finite numbers' }, { status: 400 });
      }
    }
    const float32 = Float32Array.from(body.ratios);
    await device.uploadEfficiencyCurve(float32);
    return Response.json({ ok: true, count: float32.length });
  } catch (err) {
    return errorResponse(err);
  }
}
