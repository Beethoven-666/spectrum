'use client';

import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';

const config = {
  intensity: {
    label: '强度',
    color: 'var(--chart-1)',
  },
} satisfies ChartConfig;

interface Props {
  wavelengths: number[];
  values: number[];
  /** "raw" or "actual" — only affects axis label. */
  label?: string;
}

/** Downsample to keep the SVG snappy when stream FPS is high. */
function downsample(xs: number[], ys: number[], maxPoints = 360): { x: number; y: number }[] {
  const n = xs.length;
  if (n <= maxPoints) {
    const out: { x: number; y: number }[] = new Array(n);
    for (let i = 0; i < n; i++) out[i] = { x: xs[i]!, y: ys[i]! };
    return out;
  }
  const step = n / maxPoints;
  const out: { x: number; y: number }[] = new Array(maxPoints);
  for (let i = 0; i < maxPoints; i++) {
    const idx = Math.min(n - 1, Math.floor(i * step));
    out[i] = { x: xs[idx]!, y: ys[idx]! };
  }
  return out;
}

export function SpectrumChart({ wavelengths, values, label = '强度' }: Props): React.ReactElement {
  const data = downsample(wavelengths, values);
  return (
    <ChartContainer config={config} className="aspect-[16/7] w-full">
      <AreaChart data={data} margin={{ top: 12, right: 12, bottom: 12, left: 0 }}>
        <defs>
          <linearGradient id="intensity-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-intensity)" stopOpacity={0.35} />
            <stop offset="95%" stopColor="var(--color-intensity)" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="x"
          type="number"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(v: number) => `${v.toFixed(0)}`}
          tickLine={false}
          axisLine={false}
          minTickGap={32}
          unit="nm"
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={56}
          tickFormatter={(v: number) => v.toFixed(0)}
          label={{ value: label, angle: -90, position: 'insideLeft', offset: 10, fontSize: 11 }}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelKey="x"
              labelFormatter={(_v, payload) => {
                const x = payload?.[0]?.payload?.x as number | undefined;
                return x !== undefined ? `${x.toFixed(0)} nm` : '';
              }}
              formatter={(value) => [Number(value).toFixed(2), label]}
            />
          }
        />
        <Area
          dataKey="y"
          type="monotone"
          stroke="var(--color-intensity)"
          fill="url(#intensity-fill)"
          strokeWidth={2}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}
