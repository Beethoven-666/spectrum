'use client';

import type { NirParams, BlueHazardParams } from '@h1/sdk';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { numFixed } from '@/lib/format';

interface Props {
  nir: NirParams;
  blueHazard: BlueHazardParams;
}

export function NirCard({ nir, blueHazard }: Props): React.ReactElement {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">红外 & 蓝光危害</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-4">
        <Cell label="Red Ee (701–780)" unit="W/m²" v={nir.redEe} digits={4} />
        <Cell label="NIR A (781–800)" unit="W/m²" v={nir.nirEeA} digits={4} />
        <Cell label="NIR B (>800)" unit="W/m²" v={nir.nirEeB} digits={4} />
        <Cell label="蓝光危害 Eb" unit="W/m²" v={blueHazard.Eb} digits={4} />
      </CardContent>
    </Card>
  );
}

function Cell({
  label,
  unit,
  v,
  digits = 2,
}: {
  label: string;
  unit?: string;
  v: number;
  digits?: number;
}): React.ReactElement {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono tabular-nums">
        {numFixed(v, digits)}
        {unit ? <span className="ml-0.5 text-[10px] text-muted-foreground">{unit}</span> : null}
      </span>
    </div>
  );
}
