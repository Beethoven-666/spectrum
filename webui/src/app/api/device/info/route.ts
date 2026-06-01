import type { NextRequest } from 'next/server';

import { proxyToAcquisition } from '@/lib/acquisition-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<Response> {
  return proxyToAcquisition(request, '/h1/info');
}
