import { WorkingMode } from '@h1/sdk';

import { ensureAutoConnect, requireDevice } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface Body {
  mode: 'streaming' | 'trigger';
}

export async function PUT(request: Request): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    const body = (await request.json()) as Body;
    const num = body.mode === 'trigger' ? WorkingMode.Trigger : WorkingMode.Streaming;
    await device.setWorkingMode(num);
    return Response.json({ mode: body.mode });
  } catch (err) {
    return errorResponse(err);
  }
}
