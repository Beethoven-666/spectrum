/**
 * useSpectrumStream — open the acquisition H1 stream over EventSource and
 * surface the latest frame plus FPS / drop counters.
 */

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { acquisitionPath } from './acquisition-client';
import type { SerializedSpectrumFrame } from './serialize';

export interface StreamStats {
  frameCount: number;
  fps: number;
  lastError: string | null;
  open: boolean;
  /**
   * True once the stream has been torn down for good (terminal server error or
   * too many transport drops). The UI can offer a manual retry while it is set.
   */
  stopped: boolean;
}

export interface UseSpectrumStreamOptions {
  enabled: boolean;
  tm30: boolean;
}

export interface SpectrumStreamHandle {
  frame: SerializedSpectrumFrame | null;
  stats: StreamStats;
  /** Manually re-open the stream after it has self-terminated. */
  retry: () => void;
}

/**
 * The native EventSource silently auto-reconnects (~3s) after every transport
 * drop. For the H1 stream each reconnect restarts server-side auto-exposure, so
 * an unattended browser tab can drive the spectrometer in a tight loop. We
 * therefore close the connection ourselves after a small number of consecutive
 * drops and require a manual retry, with a short bounded backoff between the
 * automatic re-opens we still allow.
 */
const MAX_TRANSPORT_DROPS = 3;
const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 8000;

export function useSpectrumStream({ enabled, tm30 }: UseSpectrumStreamOptions): SpectrumStreamHandle {
  const [frame, setFrame] = useState<SerializedSpectrumFrame | null>(null);
  const [stats, setStats] = useState<StreamStats>({
    frameCount: 0,
    fps: 0,
    lastError: null,
    open: false,
    stopped: false,
  });
  // Bumping the nonce forces the effect to re-run and open a fresh EventSource;
  // this is how `retry()` resumes after the stream has self-terminated.
  const [retryNonce, setRetryNonce] = useState(0);
  const frameTimestamps = useRef<number[]>([]);

  const retry = useCallback(() => {
    setStats((s) => ({ ...s, stopped: false, lastError: null }));
    setRetryNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    frameTimestamps.current = [];
    setStats((s) => ({ ...s, stopped: false, open: false, lastError: null }));

    const url = `${acquisitionPath('/h1/stream')}${tm30 ? '?tm30=1' : ''}`;
    let es: EventSource | null = null;
    let stopped = false;
    let drops = 0;
    let backoffTimer: ReturnType<typeof setTimeout> | null = null;

    // Tear the connection down for good: close the socket so the browser does
    // not auto-reconnect, clear the stale frame, and mark the stream stopped so
    // the UI can surface a manual retry instead of silently re-driving the H1.
    const terminate = (message: string): void => {
      stopped = true;
      if (backoffTimer) {
        clearTimeout(backoffTimer);
        backoffTimer = null;
      }
      es?.close();
      setFrame(null);
      setStats((s) => ({ ...s, open: false, stopped: true, lastError: message }));
    };

    const open = (): void => {
      if (stopped) return;
      es = new EventSource(url);

      es.addEventListener('open', () => {
        drops = 0;
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
        // we emitted server-side as `event: error`. The latter has `.data` and
        // is always terminal — stop immediately rather than reconnecting.
        const md = ev as MessageEvent;
        if (md.data) {
          try {
            const parsed = JSON.parse(md.data) as { error?: string };
            terminate(parsed?.error ?? '未知错误');
            return;
          } catch {
            // fall through to the transport-drop path
          }
        }
        if (stopped) return;
        // Transport drop. Close this socket to suppress the native auto-reconnect
        // and decide whether to retry with backoff or give up entirely.
        es?.close();
        es = null;
        drops += 1;
        if (drops >= MAX_TRANSPORT_DROPS) {
          terminate('连接中断');
          return;
        }
        const delay = Math.min(BACKOFF_BASE_MS * 2 ** (drops - 1), BACKOFF_MAX_MS);
        setStats((s) => ({ ...s, open: false, lastError: '连接中断，正在重试…' }));
        backoffTimer = setTimeout(open, delay);
      });
    };

    open();

    return () => {
      stopped = true;
      if (backoffTimer) clearTimeout(backoffTimer);
      es?.close();
      // Clear the frame so a paused/disconnected stream never shows a stale
      // "live" reading; reset open/stopped for the next subscription.
      setFrame(null);
      setStats((s) => ({ ...s, open: false, stopped: false }));
    };
  }, [enabled, tm30, retryNonce]);

  return { frame, stats, retry };
}
