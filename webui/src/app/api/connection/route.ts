/**
 * Connection lifecycle.
 *  GET    → current status
 *  POST   → connect (body: {mode:'mock'} | {mode:'serial',port?})
 *  DELETE → disconnect
 */

import { connect, disconnect, ensureAutoConnect, getStatus } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(): Promise<Response> {
  try {
    await ensureAutoConnect();
    return Response.json(getStatus());
  } catch (err) {
    return errorResponse(err);
  }
}

interface ConnectBody {
  mode: 'mock' | 'serial';
  port?: string;
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = (await request.json()) as ConnectBody;
    if (body.mode !== 'mock' && body.mode !== 'serial') {
      return Response.json({ error: 'mode must be "mock" or "serial"' }, { status: 400 });
    }
    const status = await connect(body);
    return Response.json(status);
  } catch (err) {
    return errorResponse(err);
  }
}

export async function DELETE(): Promise<Response> {
  try {
    const status = await disconnect();
    return Response.json(status);
  } catch (err) {
    return errorResponse(err);
  }
}
