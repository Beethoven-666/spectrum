'use client';

import { Camera, Download, FileJson, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';

import { NirCard } from '@/components/nir-card';
import { PhotometricGrid } from '@/components/photometric-grid';
import { PlantParamsCard } from '@/components/plant-params-card';
import { SpectrumChart } from '@/components/spectrum-chart';
import { ExposureStatusBadge } from '@/components/status-badge';
import { Tm30Section } from '@/components/tm30-section';
import { ApiCallError, apiSend } from '@/lib/api-client';
import { numFixed, numInt } from '@/lib/format';
import type { SerializedSpectrumFrame } from '@/lib/serialize';
import { useConnectionStore } from '@/store/connection';

export default function CapturePage(): React.ReactElement {
  const connected = useConnectionStore((s) => s.status.connected);
  const [tm30, setTm30] = useState(true);
  const [busy, setBusy] = useState(false);
  const [frame, setFrame] = useState<SerializedSpectrumFrame | null>(null);

  const capture = async (): Promise<void> => {
    setBusy(true);
    try {
      const url = `/api/device/capture${tm30 ? '?tm30=1' : ''}`;
      const f = await apiSend<SerializedSpectrumFrame>(url, 'POST');
      setFrame(f);
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`采集失败：${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const downloadJson = (): void => {
    if (!frame) return;
    const blob = new Blob([JSON.stringify(frame, null, 2)], { type: 'application/json' });
    triggerDownload(blob, `h1-frame-${Date.now()}.json`);
  };

  const downloadCsv = (): void => {
    if (!frame) return;
    const rows = ['wavelength_nm,raw_u16,actual'];
    for (let i = 0; i < frame.wavelengths.length; i++) {
      rows.push(`${frame.wavelengths[i]},${frame.rawSpectrum[i]},${frame.actualSpectrum[i]}`);
    }
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    triggerDownload(blob, `h1-frame-${Date.now()}.csv`);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">单帧采集</h1>
        <p className="text-sm text-muted-foreground">
          触发一次 0x32 (无 TM-30) 或 0x34 (含 TM-30) 采集，并展示完整 614 参数。
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle className="text-base">触发采集</CardTitle>
            <CardDescription>选择是否包含 TM-30 614 参数。</CardDescription>
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={tm30} onCheckedChange={setTm30} />
              <span>含 TM-30</span>
            </label>
            <Button onClick={() => void capture()} disabled={!connected || busy}>
              {busy ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 采集中…
                </>
              ) : (
                <>
                  <Camera className="mr-2 h-4 w-4" /> 采集
                </>
              )}
            </Button>
            <Button variant="outline" size="sm" onClick={downloadJson} disabled={!frame}>
              <FileJson className="mr-2 h-4 w-4" /> JSON
            </Button>
            <Button variant="outline" size="sm" onClick={downloadCsv} disabled={!frame}>
              <Download className="mr-2 h-4 w-4" /> CSV
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {frame ? (
            <>
              <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
                <Stat label="状态"><ExposureStatusBadge status={frame.exposureStatus} /></Stat>
                <Stat label="曝光时间">
                  <span className="font-mono tabular-nums">{numInt(frame.exposureTimeUs)} µs</span>
                </Stat>
                <Stat label="样本数">
                  <span className="font-mono tabular-nums">{frame.rawSpectrum.length}</span>
                </Stat>
                <Stat label="系数 N">
                  <span className="font-mono tabular-nums">
                    {frame.spectrumCoefficient}（实际 = raw / 10^N）
                  </span>
                </Stat>
                <Stat label="起始波长">
                  <span className="font-mono tabular-nums">{frame.wavelengthStart} nm</span>
                </Stat>
                <Stat label="lux">
                  <span className="font-mono tabular-nums">
                    {numFixed(frame.photometric.lux, 1)}
                  </span>
                </Stat>
              </div>
              <SpectrumChart wavelengths={frame.wavelengths} values={frame.actualSpectrum} />
            </>
          ) : (
            <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
              {connected ? '尚未采集任何帧。' : '请先连接设备。'}
            </div>
          )}
        </CardContent>
      </Card>

      {frame ? (
        <>
          <PhotometricGrid data={frame.photometric} />
          <div className="grid gap-4 lg:grid-cols-2">
            <NirCard nir={frame.nir} blueHazard={frame.blueHazard} />
            <PlantParamsCard data={frame.plant} />
          </div>
          {frame.tm30 ? <Tm30Section data={frame.tm30} /> : null}
        </>
      ) : null}
    </div>
  );
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function Stat({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span>{children}</span>
    </div>
  );
}
