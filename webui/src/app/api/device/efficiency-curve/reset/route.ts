import { ensureAutoConnect, requireDevice } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    await device.resetEfficiencyCurve();
    return Response.json({ ok: true });
  } catch (err) {
    return errorResponse(err);
  }
}
