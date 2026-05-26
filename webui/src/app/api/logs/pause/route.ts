import { setPaused } from '@/lib/log-capture';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface Body {
  paused: boolean;
}

export async function POST(request: Request): Promise<Response> {
  const body = (await request.json()) as Body;
  setPaused(Boolean(body.paused));
  return Response.json({ paused: Boolean(body.paused) });
}
