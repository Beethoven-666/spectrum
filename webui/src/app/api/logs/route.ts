import type { NextRequest } from 'next/server';

import { getLogs } from '@/lib/log-capture';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<Response> {
  const sinceIdStr = request.nextUrl.searchParams.get('sinceId');
  const sinceId = sinceIdStr ? Number(sinceIdStr) : 0;
  return Response.json(getLogs(Number.isFinite(sinceId) ? sinceId : 0));
}
