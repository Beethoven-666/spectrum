'use client';

import useSWR from 'swr';
import { Aperture, Camera, Cpu, Loader2, Ruler } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { SpectrumChart } from '@/components/spectrum-chart';
import { ExposureStatusBadge } from '@/components/status-badge';
import { ApiCallError, apiSend, fetcher } from '@/lib/api-client';
import type { SerializedSpectrumFrame } from '@/lib/serialize';
import { numFixed, numInt } from '@/lib/format';
import { useConnectionStore } from '@/store/connection';

interface DeviceInfo {
  serialNumber: string;
  wavelengthRange: { start: number; end: number };
}

interface ExposureState {
  mode: 'auto' | 'manual';
  timeUs: number;
  maxTimeUs: number;
}

export default function DebugDashboardPage(): React.ReactElement {
  const connected = useConnectionStore((s) => s.status.connected);
  const { data: info } = useSWR<DeviceInfo>(connected ? '/api/device/info' : null, fetcher);
  const { data: exposure } = useSWR<ExposureState>(
    connected ? '/api/device/exposure' : null,
    fetcher,
  );
  const [frame, setFrame] = useState<SerializedSpectrumFrame | null>(null);
  const [capturing, setCapturing] = useState(false);

  const capture = async (): Promise<void> => {
    setCapturing(true);
    try {
      const next = await apiSend<SerializedSpectrumFrame>('/api/device/capture', 'POST');
      setFrame(next);
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`采集失败：${msg}`);
    } finally {
      setCapturing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">本机 H1 调试仪表盘</h1>
        <p className="text-sm text-muted-foreground">
          直连本机串口，用于单独调试 @h1/sdk；树莓派硬件数据默认在多模态采集页面查看。
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <InfoCard
          icon={<Cpu className="h-4 w-4" />}
          label="序列号"
          value={info?.serialNumber ?? '—'}
          loading={connected && !info}
          fallback={connected ? '查询中…' : '未连接'}
        />
        <InfoCard
          icon={<Ruler className="h-4 w-4" />}
          label="波长范围"
          value={
            info ? `${info.wavelengthRange.start} – ${info.wavelengthRange.end} nm` : '—'
          }
          loading={connected && !info}
          fallback={connected ? '查询中…' : '未连接'}
        />
        <InfoCard
          icon={<Aperture className="h-4 w-4" />}
          label="曝光"
          value={
            exposure
              ? `${exposure.mode === 'auto' ? '自动' : '手动'} · ${numInt(exposure.timeUs)} µs`
              : '—'
          }
          loading={connected && !exposure}
          fallback={connected ? '查询中…' : '未连接'}
        />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle className="text-base">快速单帧采集</CardTitle>
            <CardDescription>
              点击右侧按钮发送 0x32 命令；曝光由设备根据当前模式决定。
            </CardDescription>
          </div>
          <Button onClick={() => void capture()} disabled={!connected || capturing}>
            {capturing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 采集中…
              </>
            ) : (
              <>
                <Camera className="mr-2 h-4 w-4" /> 采集
              </>
            )}
          </Button>
        </CardHeader>
        <CardContent>
          {frame ? (
            <>
              <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
                <Stat label="状态">
                  <ExposureStatusBadge status={frame.exposureStatus} />
                </Stat>
                <Stat label="曝光时间">
                  <span className="font-mono tabular-nums">{numInt(frame.exposureTimeUs)} µs</span>
                </Stat>
                <Stat label="CCT">
                  <span className="font-mono tabular-nums">
                    {numFixed(frame.photometric.CCT, 0)} K
                  </span>
                </Stat>
                <Stat label="lux">
                  <span className="font-mono tabular-nums">
                    {numFixed(frame.photometric.lux, 1)}
                  </span>
                </Stat>
                <Stat label="Ra">
                  <span className="font-mono tabular-nums">
                    {numFixed(frame.photometric.Ra, 1)}
                  </span>
                </Stat>
                <Stat label="样本数">
                  <span className="font-mono tabular-nums">{frame.rawSpectrum.length}</span>
                </Stat>
              </div>
              <SpectrumChart wavelengths={frame.wavelengths} values={frame.actualSpectrum} />
            </>
          ) : (
            <div className="flex h-64 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
              {connected ? (
                <>
                  <Camera className="h-8 w-8 text-muted-foreground/40" />
                  尚未采集任何帧，点击右上角按钮开始。
                </>
              ) : (
                '请先在顶部连接本机 H1 设备。'
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function InfoCard({
  icon,
  label,
  value,
  loading,
  fallback,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  loading?: boolean;
  fallback?: string;
}): React.ReactElement {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <span className="text-muted-foreground">{icon}</span>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-7 w-28" />
        ) : value && value !== '—' ? (
          <div className="text-lg font-semibold tabular-nums">{value}</div>
        ) : (
          <div className="text-sm text-muted-foreground">{fallback ?? '—'}</div>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span>{children}</span>
    </div>
  );
}
