'use client';

import type { PlantParams } from '@h1/sdk';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { numFixed } from '@/lib/format';

const FIELDS: Array<{ key: keyof PlantParams; label: string; unit?: string; digits?: number }> = [
  { key: 'PAR', label: 'PAR', unit: 'W/m²', digits: 3 },
  { key: 'Eca', label: 'Eca', unit: 'W/m²', digits: 3 },
  { key: 'Ecb', label: 'Ecb', unit: 'W/m²', digits: 3 },
  { key: 'Eb', label: 'Eb (蓝紫)', unit: 'W/m²', digits: 3 },
  { key: 'Ey', label: 'Ey (黄绿)', unit: 'W/m²', digits: 3 },
  { key: 'Er', label: 'Er (红橙)', unit: 'W/m²', digits: 3 },
  { key: 'Erb_ratio', label: 'Er/Eb', digits: 2 },
  { key: 'PPFD', label: 'PPFD', unit: 'µmol/(m²·s)', digits: 2 },
  { key: 'PPFDb', label: 'PPFDb', unit: 'µmol/(m²·s)', digits: 2 },
  { key: 'PPFDy', label: 'PPFDy', unit: 'µmol/(m²·s)', digits: 2 },
  { key: 'PPFDr', label: 'PPFDr', unit: 'µmol/(m²·s)', digits: 2 },
  { key: 'PPFDfr', label: 'PPFD(fr)', unit: 'µmol/(m²·s)', digits: 2 },
  { key: 'PPFDr_ratio', label: 'PPFDr 比', unit: '%', digits: 1 },
  { key: 'PPFDy_ratio', label: 'PPFDy 比', unit: '%', digits: 1 },
  { key: 'PPFDb_ratio', label: 'PPFDb 比', unit: '%', digits: 1 },
  { key: 'YPFD', label: 'YPFD', unit: 'µmol/(m²·s)', digits: 2 },
];

export function PlantParamsCard({ data }: { data: PlantParams }): React.ReactElement {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">植物生长参数</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
        {FIELDS.map((f) => {
          const v = data[f.key];
          return (
            <div key={f.key as string} className="flex items-baseline justify-between gap-2">
              <span className="text-muted-foreground">{f.label}</span>
              <span className="font-mono tabular-nums">
                {numFixed(v, f.digits ?? 2)}
                {f.unit ? <span className="ml-0.5 text-[10px] text-muted-foreground">{f.unit}</span> : null}
              </span>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
