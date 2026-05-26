'use client';

import type { PhotometricParams } from '@h1/sdk';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { numFixed } from '@/lib/format';

interface Field {
  key: keyof PhotometricParams;
  label: string;
  unit?: string;
  digits?: number;
}

const GROUPS: ReadonlyArray<{ title: string; fields: Field[] }> = [
  {
    title: 'CIE 三刺激与色度',
    fields: [
      { key: 'X', label: 'X' },
      { key: 'Y', label: 'Y' },
      { key: 'Z', label: 'Z' },
      { key: 'x', label: 'x', digits: 4 },
      { key: 'y', label: 'y', digits: 4 },
      { key: 'uk', label: 'u (1960)', digits: 4 },
      { key: 'vk', label: 'v (1960)', digits: 4 },
      { key: 'u_prime', label: "u'", digits: 4 },
      { key: 'v_prime', label: "v'", digits: 4 },
      { key: 'DUV', label: 'Duv', digits: 4 },
    ],
  },
  {
    title: '色温与显色',
    fields: [
      { key: 'CCT', label: 'CCT', unit: 'K', digits: 0 },
      { key: 'Ra', label: 'Ra', digits: 1 },
      { key: 'k', label: 'k', digits: 0 },
      { key: 'SDCM_k', label: 'SDCM/k', digits: 1 },
      { key: 'CQS', label: 'CQS', digits: 1 },
      { key: 'GAI_EES', label: 'GAI(EES)', digits: 2 },
      { key: 'GAI_BB_8', label: 'GAI(BB8)', digits: 2 },
      { key: 'GAI_BB_15', label: 'GAI(BB15)', digits: 2 },
    ],
  },
  {
    title: '特殊显色 R1–R15',
    fields: [
      { key: 'R1', label: 'R1' }, { key: 'R2', label: 'R2' },
      { key: 'R3', label: 'R3' }, { key: 'R4', label: 'R4' },
      { key: 'R5', label: 'R5' }, { key: 'R6', label: 'R6' },
      { key: 'R7', label: 'R7' }, { key: 'R8', label: 'R8' },
      { key: 'R9', label: 'R9' }, { key: 'R10', label: 'R10' },
      { key: 'R11', label: 'R11' }, { key: 'R12', label: 'R12' },
      { key: 'R13', label: 'R13' }, { key: 'R14', label: 'R14' },
      { key: 'R15', label: 'R15' },
    ],
  },
  {
    title: '光谱特征',
    fields: [
      { key: 'Lp', label: '峰值波长', unit: 'nm', digits: 1 },
      { key: 'HW', label: '半峰宽', unit: 'nm', digits: 1 },
      { key: 'Ld', label: '主波长', unit: 'nm', digits: 1 },
      { key: 'purity', label: '色纯度', unit: '%', digits: 1 },
      { key: 'r_ratio', label: 'R 比', unit: '%', digits: 1 },
      { key: 'g_ratio', label: 'G 比', unit: '%', digits: 1 },
      { key: 'b_ratio', label: 'B 比', unit: '%', digits: 1 },
      { key: 'SP', label: 'S/P', digits: 2 },
    ],
  },
  {
    title: '光度与人因',
    fields: [
      { key: 'lux', label: '照度 lux', unit: 'lx', digits: 1 },
      { key: 'fc', label: '英尺烛光', unit: 'fc', digits: 2 },
      { key: 'Nit', label: '亮度', unit: 'nit', digits: 1 },
      { key: 'Ee', label: '辐照度', unit: 'W/m²', digits: 3 },
      { key: 'EML', label: 'EML', digits: 1 },
      { key: 'M_EDI', label: 'M-EDI', digits: 1 },
    ],
  },
];

export function PhotometricGrid({ data }: { data: PhotometricParams }): React.ReactElement {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {GROUPS.map((g) => (
        <Card key={g.title}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{g.title}</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
            {g.fields.map((f) => {
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
      ))}
    </div>
  );
}
