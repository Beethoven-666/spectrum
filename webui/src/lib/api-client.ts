/**
 * Tiny fetch wrapper with consistent error handling.
 */

export interface ApiError {
  error: string;
  code?: number;
  cmdType?: number;
  status: number;
}

export class ApiCallError extends Error {
  readonly status: number;
  readonly code?: number;
  readonly cmdType?: number;

  constructor(info: ApiError) {
    super(info.error);
    this.name = 'ApiCallError';
    this.status = info.status;
    this.code = info.code;
    this.cmdType = info.cmdType;
  }
}

async function parseError(res: Response): Promise<ApiCallError> {
  let body: { error?: string; detail?: string; code?: number; cmdType?: number } = {};
  try {
    body = await res.json();
  } catch {
    body = { error: res.statusText || `HTTP ${res.status}` };
  }
  return new ApiCallError({
    error: body.error ?? body.detail ?? `HTTP ${res.status}`,
    code: body.code,
    cmdType: body.cmdType,
    status: res.status,
  });
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, cache: 'no-store' });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

export async function apiSend<T>(
  path: string,
  method: 'POST' | 'PATCH' | 'PUT' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: 'no-store',
  });
  if (!res.ok) throw await parseError(res);
  // Allow empty bodies (e.g. 204).
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const fetcher = <T>(path: string): Promise<T> => apiGet<T>(path);
