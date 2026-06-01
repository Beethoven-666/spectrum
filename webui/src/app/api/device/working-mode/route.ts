import type { NextRequest } from 'next/server';

import { proxyToAcquisition } from '@/lib/acquisition-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function PUT(request: NextRequest): Promise<Response> {
  return proxyToAcquisition(request, '/h1/working-mode', { method: 'PUT', body: request.body });
}
