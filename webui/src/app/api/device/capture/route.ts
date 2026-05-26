import type { NextRequest } from 'next/server';

import { ensureAutoConnect, requireDevice } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';
import { serializeFrame } from '@/lib/serialize';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    const tm30 = request.nextUrl.searchParams.get('tm30') === '1';
    const range = await device.getWavelengthRange();
    const frame = await device.captureSingle(tm30);
    return Response.json(serializeFrame(frame, range.start));
  } catch (err) {
    return errorResponse(err);
  }
}
