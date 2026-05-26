'use client';

import type { Tm30Params } from '@h1/sdk';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { SpectrumChart } from '@/components/spectrum-chart';
import { numFixed } from '@/lib/format';

export function Tm30Section({ data }: { data: Tm30Params }): React.ReactElement {
  // Reference spectrum is 401 samples at 380..780nm step 1nm (D-illuminant proxy).
  const wavelengths = data.referenceSpectrum.map((_v, i) => 380 + i);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">TM-30 摘要</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-end justify-between">
            <div>
              <div className="text-xs text-muted-foreground">保真度 Rf</div>
              <div className="font-mono text-2xl tabular-nums">{numFixed(data.Rf, 1)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-muted-foreground">色域 Rg</div>
              <div className="font-mono text-2xl tabular-nums">{numFixed(data.Rg, 1)}</div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <div>色差 ΔE 样本</div>
            <div className="text-right font-mono tabular-nums text-foreground">
              {data.Eab.length}
            </div>
            <div>色相偏移</div>
            <div className="text-right font-mono tabular-nums text-foreground">
              {data.hueShift.length} bins
            </div>
            <div>色品偏移</div>
            <div className="text-right font-mono tabular-nums text-foreground">
              {data.chromaShift.length} bins
            </div>
            <div>CES 颜色保真度</div>
            <div className="text-right font-mono tabular-nums text-foreground">
              {data.colorFidelity.length} bins
            </div>
          </div>
        </CardContent>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">TM-30 参考光谱（380–780 nm）</CardTitle>
        </CardHeader>
        <CardContent>
          <SpectrumChart wavelengths={wavelengths} values={data.referenceSpectrum} label="ref" />
        </CardContent>
      </Card>
    </div>
  );
}
