export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(): Promise<Response> {
  return Response.json({ ok: true, note: '关闭 EventSource 客户端即可停止流' });
}
