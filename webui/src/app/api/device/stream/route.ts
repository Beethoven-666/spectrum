/**
 * Server-Sent Events stream of SpectrumFrames.
 *
 *  - Starts the SDK streaming on first GET; stops it when the client aborts or
 *    `/api/device/stream/stop` is hit. Only one client at a time is supported
 *    (the global Device is single-port).
 *  - Each frame is emitted as: `event: frame\ndata: <json>\n\n`
 *  - A heartbeat comment is emitted every 15s to keep proxies honest.
 */

import type { NextRequest } from 'next/server';

import { ensureAutoConnect, requireDevice } from '@/lib/device-manager';
import { errorResponse } from '@/lib/api-errors';
import { serializeFrame } from '@/lib/serialize';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest): Promise<Response> {
  try {
    await ensureAutoConnect();
    const device = requireDevice();
    if (device.isStreaming()) {
      // Politely deny — caller probably forgot to stop.
      return Response.json(
        { error: '设备已在串流中，请先调用 /api/device/stream/stop' },
        { status: 409 },
      );
    }
    const tm30 = request.nextUrl.searchParams.get('tm30') === '1';
    const range = await device.getWavelengthRange();
    const encoder = new TextEncoder();

    let onFrame: ((frame: Parameters<Parameters<typeof device.on>[1]>[0]) => void) | null = null;
    let onError: ((err: Error) => void) | null = null;
    let heartbeat: NodeJS.Timeout | null = null;
    let closed = false;

    const stream = new ReadableStream<Uint8Array>({
      start: (controller) => {
        const safeClose = (): void => {
          if (closed) return;
          closed = true;
          if (heartbeat) clearInterval(heartbeat);
          if (onFrame) device.off('frame', onFrame);
          if (onError) device.off('error', onError);
          device.stopStreaming().catch(() => {
            // best-effort
          });
          try {
            controller.close();
          } catch {
            // already closed
          }
        };

        const send = (event: string, payload: unknown): void => {
          try {
            controller.enqueue(
              encoder.encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`),
            );
          } catch {
            safeClose();
          }
        };

        onFrame = (frame): void => {
          send('frame', serializeFrame(frame, range.start));
        };
        onError = (err): void => {
          send('error', { error: err.message });
        };

        device.on('frame', onFrame);
        device.on('error', onError);

        // initial padding + heartbeat
        controller.enqueue(encoder.encode(': ok\n\n'));
        heartbeat = setInterval(() => {
          try {
            controller.enqueue(encoder.encode(': hb\n\n'));
          } catch {
            safeClose();
          }
        }, 15_000);

        device.startStreaming(tm30).catch((err: unknown) => {
          send('error', { error: err instanceof Error ? err.message : String(err) });
          safeClose();
        });

        request.signal.addEventListener('abort', safeClose);
      },
      cancel: () => {
        if (heartbeat) clearInterval(heartbeat);
        if (onFrame) device.off('frame', onFrame);
        if (onError) device.off('error', onError);
        device.stopStreaming().catch(() => {});
      },
    });

    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (err) {
    return errorResponse(err);
  }
}
