'use client';

import { Pause, Play } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';

import { SpectrumChart } from '@/components/spectrum-chart';
import { ExposureStatusBadge } from '@/components/status-badge';
import { numFixed, numInt } from '@/lib/format';
import { useSpectrumStream } from '@/lib/sse';
import {
  acquisitionPath,
  type AcquisitionDevices,
  type AcquisitionHealth,
} from '@/lib/acquisition-client';
import { fetcher } from '@/lib/api-client';
import useSWR from 'swr';

export default function StreamPage(): React.ReactElement {
  const { data: health } = useSWR<AcquisitionHealth>(
    acquisitionPath('/health'),
    fetcher,
    { refreshInterval: 5_000 },
  );
  const { data: devices } = useSWR<AcquisitionDevices>(
    acquisitionPath('/devices'),
    fetcher,
    { refreshInterval: 5_000 },
  );
  const connected = health?.ok === true && devices?.h1?.status === 'ready';
  const [running, setRunning] = useState(false);
  const [tm30, setTm30] = useState(false);
  const { frame, stats } = useSpectrumStream({ enabled: running && connected, tm30 });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">H1 实时光谱流</h1>
        <p className="text-sm text-muted-foreground">
          通过树莓派 acquisition 服务接收真实 H1 0x33 / 0x35 流式帧，启动前会先执行自动曝光。
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle className="text-base">流控制</CardTitle>
            <CardDescription>采集服务串行访问 H1 串口，样本采集与实时流不会并发打开设备。</CardDescription>
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={tm30} onCheckedChange={setTm30} disabled={running} />
              <span>含 TM-30</span>
            </label>
            <Button
              variant={running ? 'destructive' : 'default'}
              onClick={() => setRunning((r) => !r)}
              disabled={!connected}
            >
              {running ? (
                <>
                  <Pause className="mr-2 h-4 w-4" /> 停止
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" /> 开始
                </>
              )}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <Badge variant={stats.open ? 'default' : 'secondary'}>
              {stats.open ? '已连接 SSE' : '已停止'}
            </Badge>
            <Stat label="FPS">{numFixed(stats.fps, 1)}</Stat>
            <Stat label="累计帧">{numInt(stats.frameCount)}</Stat>
            {frame ? (
              <>
                <Stat label="状态"><ExposureStatusBadge status={frame.exposureStatus} /></Stat>
                <Stat label="曝光">
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
              </>
            ) : null}
            {stats.lastError ? (
              <span className="text-xs text-destructive">{stats.lastError}</span>
            ) : null}
          </div>
          {frame ? (
            <SpectrumChart wavelengths={frame.wavelengths} values={frame.actualSpectrum} />
          ) : (
            <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
              {connected
                ? running
                  ? '正在执行自动曝光并等待第一帧…'
                  : '点击开始按钮启动树莓派 H1 串流。'
                : '等待树莓派 H1 就绪。'}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
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
