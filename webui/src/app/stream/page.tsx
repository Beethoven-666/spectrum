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
import { useConnectionStore } from '@/store/connection';

export default function StreamPage(): React.ReactElement {
  const connected = useConnectionStore((s) => s.status.connected);
  const [running, setRunning] = useState(false);
  const [tm30, setTm30] = useState(false);
  const { frame, stats } = useSpectrumStream({ enabled: running && connected, tm30 });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">实时光谱流</h1>
        <p className="text-sm text-muted-foreground">
          通过 SSE 接收 0x33 / 0x35 流式帧。停止流时会自动调用 0x04。
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle className="text-base">流控制</CardTitle>
            <CardDescription>仅允许一个客户端同时串流。</CardDescription>
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
                  ? '等待第一帧…'
                  : '点击开始按钮启动 SSE 串流。'
                : '请先连接设备。'}
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
