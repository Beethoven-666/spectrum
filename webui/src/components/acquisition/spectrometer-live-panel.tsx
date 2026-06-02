'use client';

import { Camera, Pause, Play } from 'lucide-react';
import { useMemo, useState } from 'react';

import { SpectrumChart } from '@/components/spectrum-chart';
import { ExposureStatusBadge } from '@/components/status-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { acquisitionPath } from '@/lib/acquisition-client';
import { numFixed, numInt } from '@/lib/format';
import { useSpectrumStream } from '@/lib/sse';

type SpectrometerLivePanelProps = {
  serviceOk: boolean;
  h1Ready: boolean;
  mainRgbStatus?: string;
  mainRgbDetail?: string;
  previewVersion: number;
  disabled?: boolean;
};

export function SpectrometerLivePanel({
  serviceOk,
  h1Ready,
  mainRgbStatus,
  mainRgbDetail,
  previewVersion,
  disabled = false,
}: SpectrometerLivePanelProps): React.ReactElement {
  const [running, setRunning] = useState(true);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);

  // streamAllowed already gates on !disabled, so the H1 stream pauses during a
  // capture and resumes afterwards without needing an effect to flip `running`.
  const streamAllowed = serviceOk && h1Ready && !disabled;
  const mainRgbReady = mainRgbStatus === 'ready';
  const { frame, stats } = useSpectrumStream({ enabled: running && streamAllowed, tm30: false });

  const mainRgbUrl = useMemo(
    () => `${acquisitionPath('/preview/main_rgb/frame')}?v=${previewVersion}`,
    [previewVersion],
  );
  // Derive the failed flag from the URL so it resets automatically when the
  // preview version advances (no set-state-in-effect needed).
  const mainRgbFailed = failedUrl === mainRgbUrl;

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="text-base">H1 光谱 / 主 RGB</CardTitle>
          <CardDescription>
            分光镜对齐视场：主 RGB 预览与 H1 实时光谱同屏对照；采集时会自动停止光谱流。
          </CardDescription>
        </div>
        <Button
          variant={running ? 'destructive' : 'default'}
          size="sm"
          onClick={() => setRunning((current) => !current)}
          disabled={!streamAllowed}
        >
          {running ? (
            <>
              <Pause className="h-4 w-4" />
              停止光谱流
            </>
          ) : (
            <>
              <Play className="h-4 w-4" />
              开始光谱流
            </>
          )}
        </Button>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <MainRgbPreview
          ready={serviceOk && mainRgbReady}
          url={mainRgbUrl}
          failed={mainRgbFailed}
          detail={mainRgbDetail}
          onError={() => setFailedUrl(mainRgbUrl)}
        />
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            <Badge variant={stats.open ? 'default' : 'secondary'}>
              {stats.open ? '光谱流已连接' : running ? '连接中…' : '光谱流已停止'}
            </Badge>
            {stats.open ? (
              <>
                <StreamStat label="FPS">{numFixed(stats.fps, 1)}</StreamStat>
                <StreamStat label="帧数">{numInt(stats.frameCount)}</StreamStat>
              </>
            ) : null}
            {frame ? (
              <>
                <StreamStat label="状态">
                  <ExposureStatusBadge status={frame.exposureStatus} />
                </StreamStat>
                <StreamStat label="曝光">
                  <span className="font-mono tabular-nums">{numInt(frame.exposureTimeUs)} µs</span>
                </StreamStat>
                <StreamStat label="CCT">
                  <span className="font-mono tabular-nums">{numFixed(frame.photometric.CCT, 0)} K</span>
                </StreamStat>
              </>
            ) : null}
            {stats.lastError ? <span className="text-xs text-destructive">{stats.lastError}</span> : null}
          </div>
          {frame ? (
            <div className="rounded-md border p-2">
              <SpectrumChart wavelengths={frame.wavelengths} values={frame.actualSpectrum} />
            </div>
          ) : (
            <div className="flex min-h-56 flex-col items-center justify-center gap-2 rounded-md border bg-muted/30 px-4 text-center text-sm text-muted-foreground">
              {!serviceOk ? (
                '等待采集服务'
              ) : !h1Ready ? (
                'H1 未就绪'
              ) : disabled ? (
                '采集中，光谱流已暂停'
              ) : running ? (
                '正在执行自动曝光并等待第一帧…'
              ) : (
                '点击右上角开始光谱流，与主 RGB 对照视场'
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function MainRgbPreview({
  ready,
  url,
  failed,
  detail,
  onError,
}: {
  ready: boolean;
  url: string;
  failed: boolean;
  detail?: string;
  onError: () => void;
}): React.ReactElement {
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">主 RGB（光谱仪视场）</div>
      {!ready || failed ? (
        <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded-md border bg-muted/30 px-4 text-center text-sm text-muted-foreground">
          <Camera className="h-8 w-8 text-muted-foreground/40" />
          <div>{failed ? '主 RGB 预览不可用' : '主 RGB 未接入'}</div>
          {detail ? <div className="max-w-xs text-xs">{detail}</div> : null}
        </div>
      ) : (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={url}
          alt="Main RGB preview"
          className="aspect-video w-full rounded-md border object-cover"
          onError={onError}
        />
      )}
    </div>
  );
}

function StreamStat({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span>{children}</span>
    </div>
  );
}
