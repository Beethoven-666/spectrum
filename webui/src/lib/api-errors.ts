/**
 * Shared error → Response helpers for API Route Handlers.
 */

import { DeviceError, H1Error } from '@h1/sdk';

interface ErrorBody {
  error: string;
  code?: number;
  cmdType?: number;
}

export function errorResponse(err: unknown): Response {
  if (err instanceof DeviceError) {
    const body: ErrorBody = {
      error: err.message,
      code: err.code,
      cmdType: err.cmdType,
    };
    return Response.json(body, { status: 502 });
  }
  if (err instanceof H1Error) {
    const body: ErrorBody = { error: err.message };
    return Response.json(body, { status: 502 });
  }
  const message = err instanceof Error ? err.message : String(err);
  const body: ErrorBody = { error: message };
  return Response.json(body, { status: 500 });
}
