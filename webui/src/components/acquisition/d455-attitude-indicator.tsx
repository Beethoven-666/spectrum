'use client';

import { useId } from 'react';

import { Badge } from '@/components/ui/badge';
import type { D455ImuPayload } from '@/lib/acquisition-client';

type D455AttitudeIndicatorProps = {
  imu?: D455ImuPayload;
  loading?: boolean;
  maxDeltaDeg?: number;
};

export function D455AttitudeIndicator({
  imu,
  loading = false,
  maxDeltaDeg = 8,
}: D455AttitudeIndicatorProps): React.ReactElement {
  const clipId = useId();

  if (loading) {
    return (
      <div className="flex min-h-28 items-center justify-center rounded-md border bg-muted/20 text-sm text-muted-foreground">
        读取 IMU…
      </div>
    );
  }

  if (!imu?.available) {
    return (
      <div className="flex min-h-28 flex-col items-center justify-center gap-1 rounded-md border bg-muted/20 px-4 text-center text-sm text-muted-foreground">
        <div>IMU 不可用</div>
        {imu?.error ? <div className="text-xs">{imu.error}</div> : null}
        {imu?.enabled === false ? <div className="text-xs">已降级为仅 color/depth</div> : null}
      </div>
    );
  }

  const rollDeg = numberOrZero(imu.roll_deg);
  const pitchDeg = numberOrZero(imu.pitch_deg);
  const deltaRoll = Math.abs(numberOrZero(imu.delta_roll_deg));
  const deltaPitch = Math.abs(numberOrZero(imu.delta_pitch_deg));
  const motionWarn = deltaRoll > maxDeltaDeg || deltaPitch > maxDeltaDeg;
  const pitchOffset = clamp(pitchDeg, -45, 45) * (36 / 45);

  return (
    <div className="flex flex-col gap-3 rounded-md border bg-muted/10 p-3 sm:flex-row sm:items-center">
      <div className="relative mx-auto h-28 w-28 shrink-0 sm:mx-0">
        <svg viewBox="0 0 100 100" className="h-full w-full" aria-label="D455 姿态指示">
          <circle cx="50" cy="50" r="48" fill="hsl(var(--background))" stroke="currentColor" strokeOpacity="0.15" />
          <clipPath id={clipId}>
            <circle cx="50" cy="50" r="46" />
          </clipPath>
          <g clipPath={`url(#${clipId})`}>
            <g transform={`rotate(${rollDeg} 50 50) translate(0 ${pitchOffset})`}>
              <rect x="-60" y="-80" width="220" height="80" fill="#3b82f6" opacity="0.55" />
              <rect x="-60" y="0" width="220" height="80" fill="#92400e" opacity="0.55" />
              <line x1="-60" y1="0" x2="160" y2="0" stroke="white" strokeWidth="1.5" opacity="0.9" />
            </g>
          </g>
          <line x1="32" y1="50" x2="68" y2="50" stroke="#f97316" strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="50" cy="50" r="2.5" fill="#f97316" />
          <circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" strokeOpacity="0.2" />
        </svg>
      </div>
      <div className="min-w-0 flex-1 space-y-2 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">IMU 姿态</span>
          {motionWarn ? <Badge variant="secondary">抖动</Badge> : <Badge variant="default">稳定</Badge>}
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono tabular-nums">
          <Metric label="Roll" value={`${rollDeg.toFixed(1)}°`} />
          <Metric label="Pitch" value={`${pitchDeg.toFixed(1)}°`} />
          <Metric label="Δ Roll" value={`${deltaRoll.toFixed(1)}°`} warn={deltaRoll > maxDeltaDeg} />
          <Metric label="Δ Pitch" value={`${deltaPitch.toFixed(1)}°`} warn={deltaPitch > maxDeltaDeg} />
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, warn = false }: { label: string; value: string; warn?: boolean }): React.ReactElement {
  return (
    <div>
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
      <div className={warn ? 'text-amber-600 dark:text-amber-400' : undefined}>{value}</div>
    </div>
  );
}

function numberOrZero(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
