import type { NextRequest } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;

  // M16 (SSRF) hardening. Building the target with
  // `new URL(path.join('/'), base)` is unsafe: a catch-all segment that itself
  // contains a scheme (e.g. /api/acquisition/https:/evil.com/x) is parsed as an
  // absolute URL and overrides `base`, letting the proxy fetch an attacker URL.
  // Instead, reject any segment containing ':' or '\' (scheme / UNC smuggling),
  // then assign the pathname onto the trusted base origin and assert the origin
  // is unchanged before fetching.
  for (const segment of path) {
    if (segment.includes(':') || segment.includes('\\')) {
      return new Response('Invalid path segment', { status: 400 });
    }
  }

  const base = new URL(baseUrl());
  const upstream = new URL(baseUrl());
  // Segments arrive already URL-decoded from the catch-all route; re-encode each
  // so reserved characters cannot alter the path structure or origin.
  upstream.pathname = '/' + path.map(encodeURIComponent).join('/');
  upstream.search = request.nextUrl.search;

  // Defense in depth: the target must never leave the trusted acquisition origin.
  if (upstream.origin !== base.origin) {
    return new Response('Invalid upstream target', { status: 400 });
  }

  const headers = new Headers();
  const contentType = request.headers.get('content-type');
  const accept = request.headers.get('accept');
  if (contentType) headers.set('content-type', contentType);
  if (accept) headers.set('accept', accept);

  // H1 pairing: when an API token is configured, authenticate to the acquisition
  // service. Default (unset/empty) sends no header, preserving prior behavior.
  const apiToken = process.env.ACQUISITION_API_TOKEN;
  if (apiToken) headers.set('authorization', `Bearer ${apiToken}`);

  const res = await fetch(upstream, {
    method: request.method,
    headers,
    body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
    cache: 'no-store',
    duplex: request.method === 'GET' || request.method === 'HEAD' ? undefined : 'half',
  } as RequestInit & { duplex?: 'half' });

  const outHeaders = new Headers();
  for (const key of ['content-type', 'content-disposition', 'cache-control']) {
    const value = res.headers.get(key);
    if (value) outHeaders.set(key, value);
  }
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers: outHeaders,
  });
}

function baseUrl(): string {
  return process.env.ACQUISITION_API_BASE_URL ?? DEFAULT_BASE_URL;
}
