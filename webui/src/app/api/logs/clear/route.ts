import { clearLogs } from '@/lib/log-capture';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(): Promise<Response> {
  clearLogs();
  return Response.json({ ok: true });
}
