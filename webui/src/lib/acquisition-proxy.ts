/**
 * Proxy Next.js Route Handlers to the acquisition service.
 */

import type { NextRequest } from 'next/server';

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';

export function acquisitionBaseUrl(): string {
  return process.env.ACQUISITION_API_BASE_URL ?? DEFAULT_BASE_URL;
}

export async function proxyToAcquisition(
  request: NextRequest,
  upstreamPath: string,
  init?: { method?: string; body?: BodyInit | null; search?: string },
): Promise<Response> {
  const upstream = new URL(upstreamPath.replace(/^\//, ''), withTrailingSlash(acquisitionBaseUrl()));
  upstream.search = init?.search ?? new URL(request.url).search;

  const headers = new Headers();
  const contentType = request.headers.get('content-type');
  const accept = request.headers.get('accept');
  if (contentType) headers.set('content-type', contentType);
  if (accept) headers.set('accept', accept);

  const method = init?.method ?? request.method;
  let body: BodyInit | null | undefined = init?.body;
  if (body === undefined) {
    body = method === 'GET' || method === 'HEAD' ? undefined : request.body;
  }

  const res = await fetch(upstream, {
    method,
    headers,
    body,
    cache: 'no-store',
    duplex: method === 'GET' || method === 'HEAD' ? undefined : 'half',
  } as RequestInit & { duplex?: 'half' });

  const outHeaders = new Headers();
  for (const key of ['content-type', 'content-disposition', 'cache-control', 'connection']) {
    const value = res.headers.get(key);
    if (value) outHeaders.set(key, value);
  }
  if (res.headers.get('content-type')?.includes('text/event-stream')) {
    outHeaders.set('X-Accel-Buffering', 'no');
  }

  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers: outHeaders,
  });
}

function withTrailingSlash(value: string): string {
  return value.endsWith('/') ? value : `${value}/`;
}
