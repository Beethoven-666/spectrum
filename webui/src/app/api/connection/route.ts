/**
 * Connection lifecycle — reflects acquisition H1 gateway status.
 *  GET    → current status from acquisition /devices
 *  POST   → not supported (410)
 *  DELETE → not supported (410)
 */

import { acquisitionBaseUrl } from '@/lib/acquisition-proxy';
import { GATEWAY_DISCONNECTED, type ConnectionStatus } from '@/lib/device-manager';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface DevicesResponse {
  h1?: {
    status?: string;
    serial_number?: string | null;
    detail?: { port?: string; error?: string };
  };
}

export async function GET(): Promise<Response> {
  try {
    const res = await fetch(`${acquisitionBaseUrl()}/devices`, { cache: 'no-store' });
    if (!res.ok) {
      return Response.json(GATEWAY_DISCONNECTED satisfies ConnectionStatus);
    }
    const devices = (await res.json()) as DevicesResponse;
    const h1 = devices.h1;
    const status: ConnectionStatus = {
      connected: h1?.status === 'ready',
      mode: 'gateway',
      port: typeof h1?.detail?.port === 'string' ? h1.detail.port : null,
      openedAt: null,
      serialNumber: h1?.serial_number ?? null,
      status: h1?.status ?? 'error',
    };
    return Response.json(status);
  } catch {
    return Response.json(GATEWAY_DISCONNECTED satisfies ConnectionStatus);
  }
}

export async function POST(): Promise<Response> {
  return Response.json(
    { error: 'H1 由 acquisition 服务统一管理，无需手动连接' },
    { status: 410 },
  );
}

export async function DELETE(): Promise<Response> {
  return Response.json(
    { error: 'H1 由 acquisition 服务统一管理，无法手动断开' },
    { status: 410 },
  );
}
