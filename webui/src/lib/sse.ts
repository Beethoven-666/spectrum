/**
 * useSpectrumStream — open `/api/device/stream` over EventSource and surface
 * the latest frame plus FPS / drop counters.
 */

'use client';

import { useEffect, useRef, useState } from 'react';

import type { SerializedSpectrumFrame } from './serialize';

export interface StreamStats {
  frameCount: number;
  fps: number;
  lastError: string | null;
  open: boolean;
}

export interface UseSpectrumStreamOptions {
  enabled: boolean;
  tm30: boolean;
}

export interface SpectrumStreamHandle {
  frame: SerializedSpectrumFrame | null;
  stats: StreamStats;
}

export function useSpectrumStream({ enabled, tm30 }: UseSpectrumStreamOptions): SpectrumStreamHandle {
  const [frame, setFrame] = useState<SerializedSpectrumFrame | null>(null);
  const [stats, setStats] = useState<StreamStats>({
    frameCount: 0,
    fps: 0,
    lastError: null,
    open: false,
  });
  const frameTimestamps = useRef<number[]>([]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const url = `/api/device/stream${tm30 ? '?tm30=1' : ''}`;
    const es = new EventSource(url);
    let stopped = false;

    es.addEventListener('open', () => {
      setStats((s) => ({ ...s, open: true, lastError: null }));
    });

    es.addEventListener('frame', (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as SerializedSpectrumFrame;
        const now = performance.now();
        const ts = frameTimestamps.current;
        ts.push(now);
        while (ts.length > 0 && now - ts[0]! > 1000) ts.shift();
        const fps = ts.length;
        setFrame(data);
        setStats((s) => ({
          ...s,
          frameCount: s.frameCount + 1,
          fps,
        }));
      } catch (err) {
        setStats((s) => ({
          ...s,
          lastError: err instanceof Error ? err.message : String(err),
        }));
      }
    });

    es.addEventListener('error', (ev) => {
      // EventSource fires `error` for both transport drops and message events
      // we emitted server-side as `event: error`. The latter has `.data`.
      const md = ev as MessageEvent;
      if (md.data) {
        try {
          const parsed = JSON.parse(md.data) as { error?: string };
          if (parsed?.error) {
            setStats((s) => ({ ...s, lastError: parsed.error ?? '未知错误' }));
            return;
          }
        } catch {
          // fall through
        }
      }
      if (!stopped) {
        setStats((s) => ({ ...s, open: false, lastError: '连接中断' }));
      }
    });

    return () => {
      stopped = true;
      es.close();
      // Best-effort tell server to stop. Don't await; component is unmounting.
      void fetch('/api/device/stream/stop', { method: 'POST' });
      setStats((s) => ({ ...s, open: false }));
    };
  }, [enabled, tm30]);

  return { frame, stats };
}
