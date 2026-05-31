'use client';

import useSWR from 'swr';
import {
  AlertTriangle,
  Download,
  ExternalLink,
  FileJson,
  Image as ImageIcon,
  LineChart,
  Maximize2,
  ScanLine,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import { SpectrumChart } from '@/components/spectrum-chart';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  acquisitionPath,
  type SampleDetailResponse,
  type SampleSpectrum,
} from '@/lib/acquisition-client';
import { fetcher } from '@/lib/api-client';
import { cn } from '@/lib/utils';

type SamplePreviewSheetProps = {
  sampleId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function SamplePreviewSheet({
  sampleId,
  open,
  onOpenChange,
}: SamplePreviewSheetProps): React.ReactElement | null {
  const detailKey = open && sampleId ? acquisitionPath(`/samples/${sampleId}`) : null;
  const { data: detail, error, isLoading } = useSWR<SampleDetailResponse>(detailKey, fetcher);

  if (!sampleId) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-hidden p-0 data-[side=right]:w-full sm:max-w-none md:data-[side=right]:w-[760px] lg:data-[side=right]:w-[920px]">
        <SheetHeader className="border-b pr-14">
          <SheetTitle>样本预览</SheetTitle>
          <SheetDescription className="break-all font-mono text-xs">{sampleId}</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          {isLoading ? <PreviewSkeleton /> : null}
          {error ? <PreviewError message={errorMessage(error)} /> : null}
          {detail ? <SamplePreviewTabs sampleId={sampleId} detail={detail} /> : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function SamplePreviewTabs({
  sampleId,
  detail,
}: {
  sampleId: string;
  detail: SampleDetailResponse;
}): React.ReactElement {
  return (
    <Tabs defaultValue="overview" className="pt-4">
      <TabsList className="grid w-full grid-cols-4">
        <TabsTrigger value="overview">
          <ScanLine className="h-4 w-4" />
          概览
        </TabsTrigger>
        <TabsTrigger value="d455">
          <ImageIcon className="h-4 w-4" />
          D455
        </TabsTrigger>
        <TabsTrigger value="spectrum">
          <LineChart className="h-4 w-4" />
          H1
        </TabsTrigger>
        <TabsTrigger value="json">
          <FileJson className="h-4 w-4" />
          JSON
        </TabsTrigger>
      </TabsList>

      <TabsContent value="overview" className="mt-4">
        <SampleOverview sampleId={sampleId} detail={detail} />
      </TabsContent>
      <TabsContent value="d455" className="mt-4">
        <SampleD455Preview sampleId={sampleId} detail={detail} />
      </TabsContent>
      <TabsContent value="spectrum" className="mt-4">
        <SampleSpectrumPreview sampleId={sampleId} />
      </TabsContent>
      <TabsContent value="json" className="mt-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <JsonBlock title="metadata.json" value={detail.metadata} />
          <JsonBlock title="quality.json" value={detail.quality} />
        </div>
      </TabsContent>
    </Tabs>
  );
}

function SampleOverview({
  sampleId,
  detail,
}: {
  sampleId: string;
  detail: SampleDetailResponse;
}): React.ReactElement {
  const metadata = detail.metadata;
  const quality = detail.quality;
  const devices = recordValue(metadata.devices);
  const mainRgb = recordValue(devices?.main_rgb);
  const geometry = recordValue(quality.geometry);
  const h1 = recordValue(quality.h1);
  const warnings = stringArray(quality.warnings) ?? detail.index.warnings;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(260px,0.65fr)]">
      <ImagePanel
        src={acquisitionPath(`/samples/${sampleId}/preview`)}
        alt={`${sampleId} ROI preview`}
        label="ROI 预览"
        className="aspect-video"
      />
      <div className="space-y-4 rounded-md border p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium">质量</div>
            <div className="text-xs text-muted-foreground">{formatDate(detail.index.created_at)}</div>
          </div>
          <QualityBadge status={detail.index.quality_status} />
        </div>
        <Separator />
        <div className="grid gap-3 sm:grid-cols-2">
          <KeyValue label="距离" value={formatMm(numberValue(geometry?.distance_mm) ?? detail.index.distance_mm)} />
          <KeyValue label="角度" value={formatDeg(numberValue(geometry?.angle_deg) ?? detail.index.angle_deg)} />
          <KeyValue label="曝光" value={stringValue(h1?.exposure_status) ?? detail.index.h1_exposure_status ?? '-'} />
          <KeyValue label="主 RGB" value={stringValue(mainRgb?.status) ?? detail.index.main_rgb_status ?? '-'} />
          <KeyValue label="标定" value={detail.index.calibration_version ?? '-'} />
          <KeyValue label="大小" value={formatBytes(detail.index.size_bytes)} />
        </div>
        {warnings.length > 0 ? (
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">Warnings</div>
            <div className="flex flex-wrap gap-2">
              {warnings.map((warning) => (
                <Badge key={warning} variant="secondary">
                  {warning}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
        <a
          href={acquisitionPath(`/samples/${sampleId}/download`)}
          className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'w-full')}
        >
          <Download className="h-4 w-4" />
          下载样本包
        </a>
      </div>
    </div>
  );
}

function SampleD455Preview({
  sampleId,
  detail,
}: {
  sampleId: string;
  detail: SampleDetailResponse;
}): React.ReactElement {
  const d455 = recordValue(recordValue(detail.metadata.devices)?.d455);
  const profile = recordValue(d455?.profile);
  const intrinsics = recordValue(d455?.intrinsics);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <ImagePanel
          src={acquisitionPath(`/samples/${sampleId}/files/d455/color.jpg`)}
          alt={`${sampleId} D455 color`}
          label="D455 Color"
          className="aspect-video"
        />
        <ImagePanel
          src={acquisitionPath(`/samples/${sampleId}/files/d455/depth.png`)}
          alt={`${sampleId} D455 depth`}
          label="D455 Depth"
          className="aspect-video"
          imageClassName="object-contain"
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <InfoPanel title="设备">
          <KeyValue label="状态" value={stringValue(d455?.status) ?? '-'} />
          <KeyValue label="序列号" value={stringValue(d455?.serial) ?? '-'} />
        </InfoPanel>
        <InfoPanel title="Profile">
          <CompactJson value={profile ?? {}} />
        </InfoPanel>
        <InfoPanel title="Intrinsics">
          <CompactJson value={intrinsics ?? {}} />
        </InfoPanel>
      </div>
    </div>
  );
}

function SampleSpectrumPreview({ sampleId }: { sampleId: string }): React.ReactElement {
  const spectrumKey = acquisitionPath(`/samples/${sampleId}/files/h1/spectrum.json`);
  const { data, error, isLoading } = useSWR<SampleSpectrum>(spectrumKey, fetcher);
  const wavelengths = numberArray(data?.wavelengths);
  const values = numberArray(data?.actual_spectrum) ?? numberArray(data?.raw_spectrum);
  const photometric = recordValue(data?.photometric);
  const selectedAttempt = recordValue(data?.selected_attempt);

  if (isLoading) return <PreviewSkeleton compact />;
  if (error) return <PreviewError message={errorMessage(error)} />;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricBox label="曝光状态" value={stringValue(selectedAttempt?.exposure_status) ?? '-'} />
        <MetricBox label="曝光时间" value={formatUs(numberValue(selectedAttempt?.exposure_time_us))} />
        <MetricBox label="CCT" value={formatMaybeNumber(numberValue(photometric?.CCT), ' K', 0)} />
        <MetricBox label="lux" value={formatMaybeNumber(numberValue(photometric?.lux), '', 1)} />
      </div>
      {wavelengths && values && wavelengths.length === values.length ? (
        <div className="rounded-md border p-3">
          <SpectrumChart wavelengths={wavelengths} values={values} />
        </div>
      ) : (
        <EmptyPanel title="该样本没有可绘制光谱" detail="需要 h1/spectrum.json 中同时包含 wavelengths 和 actual_spectrum。" />
      )}
      <JsonBlock title="h1/spectrum.json" value={data ?? {}} />
    </div>
  );
}

function ImagePanel({
  src,
  alt,
  label,
  className,
  imageClassName,
}: {
  src: string;
  alt: string;
  label: string;
  className?: string;
  imageClassName?: string;
}): React.ReactElement {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const failed = failedSrc === src;

  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      {failed ? (
        <div className={cn('flex items-center justify-center overflow-hidden rounded-md border bg-muted/30', className)}>
          <div className="flex flex-col items-center gap-2 px-4 text-center text-sm text-muted-foreground">
            <ImageIcon className="h-8 w-8 text-muted-foreground/50" />
            图片不可用
          </div>
        </div>
      ) : (
        <Dialog>
          <DialogTrigger
            render={
              <button
                type="button"
                className={cn(
                  'group relative flex items-center justify-center overflow-hidden rounded-md border bg-muted/30 text-left outline-none transition focus-visible:ring-[3px] focus-visible:ring-ring/50',
                  className,
                )}
              />
            }
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={src}
              alt={alt}
              className={cn('h-full w-full object-cover', imageClassName)}
              onError={() => setFailedSrc(src)}
            />
            <span className="absolute right-2 bottom-2 inline-flex items-center gap-1 rounded-md bg-background/85 px-2 py-1 text-xs text-foreground opacity-0 shadow-sm backdrop-blur transition group-hover:opacity-100 group-focus-visible:opacity-100">
              <Maximize2 className="h-3.5 w-3.5" />
              大图
            </span>
          </DialogTrigger>
          <DialogContent className="max-w-[calc(100vw-1rem)] gap-0 overflow-hidden p-0 sm:max-w-[calc(100vw-2rem)] lg:max-w-6xl">
            <DialogHeader className="border-b px-4 py-3 pr-14">
              <DialogTitle>{label}</DialogTitle>
              <DialogDescription className="break-all font-mono text-xs">{alt}</DialogDescription>
            </DialogHeader>
            <div className="flex max-h-[calc(100vh-9rem)] min-h-[280px] items-center justify-center bg-black/90 p-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={src} alt={alt} className="max-h-[calc(100vh-10rem)] max-w-full object-contain" />
            </div>
            <DialogFooter className="m-0 rounded-none">
              <a
                href={src}
                target="_blank"
                rel="noreferrer"
                className={buttonVariants({ variant: 'outline', size: 'sm' })}
              >
                <ExternalLink className="h-4 w-4" />
                在新标签打开原图
              </a>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

function InfoPanel({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div className="min-w-0 space-y-3 rounded-md border p-3">
      <div className="text-sm font-medium">{title}</div>
      {children}
    </div>
  );
}

function JsonBlock({ title, value }: { title: string; value: unknown }): React.ReactElement {
  const formatted = useMemo(() => JSON.stringify(value ?? {}, null, 2), [value]);
  return (
    <div className="min-w-0 space-y-2">
      <div className="text-xs text-muted-foreground">{title}</div>
      <pre className="max-h-[420px] overflow-auto rounded-md border bg-muted/30 p-3 text-xs leading-relaxed whitespace-pre-wrap break-words">
        {formatted}
      </pre>
    </div>
  );
}

function CompactJson({ value }: { value: unknown }): React.ReactElement {
  const formatted = useMemo(() => JSON.stringify(value ?? {}, null, 2), [value]);
  return (
    <pre className="max-h-40 overflow-auto rounded-md bg-muted/40 p-2 text-xs leading-relaxed whitespace-pre-wrap break-words">
      {formatted}
    </pre>
  );
}

function KeyValue({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="truncate font-mono text-xs">{value}</div>
    </div>
  );
}

function MetricBox({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-sm">{value}</div>
    </div>
  );
}

function QualityBadge({ status }: { status: 'good' | 'warn' | 'bad' }): React.ReactElement {
  const variant = status === 'good' ? 'default' : status === 'warn' ? 'secondary' : 'destructive';
  return <Badge variant={variant}>{status}</Badge>;
}

function PreviewSkeleton({ compact = false }: { compact?: boolean }): React.ReactElement {
  return (
    <div className="space-y-4 pt-4">
      <Skeleton className="h-8 w-full" />
      <div className={cn('grid gap-4', compact ? 'grid-cols-1' : 'lg:grid-cols-2')}>
        <Skeleton className="aspect-video w-full" />
        <Skeleton className="aspect-video w-full" />
      </div>
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

function PreviewError({ message }: { message: string }): React.ReactElement {
  return (
    <div className="mt-4 flex items-start gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
      <div>
        <div className="font-medium text-destructive">样本预览不可用</div>
        <div className="mt-1 text-muted-foreground">{message}</div>
      </div>
    </div>
  );
}

function EmptyPanel({ title, detail }: { title: string; detail: string }): React.ReactElement {
  return (
    <div className="flex min-h-56 flex-col items-center justify-center rounded-md border bg-muted/30 px-4 text-center">
      <LineChart className="h-8 w-8 text-muted-foreground/50" />
      <div className="mt-3 text-sm font-medium">{title}</div>
      <div className="mt-1 max-w-md text-xs text-muted-foreground">{detail}</div>
    </div>
  );
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function numberArray(value: unknown): number[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === 'number' && Number.isFinite(item))
    ? value
    : null;
}

function stringArray(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatMm(value: number | null): string {
  return value === null ? '-' : `${value.toFixed(0)} mm`;
}

function formatDeg(value: number | null): string {
  return value === null ? '-' : `${value.toFixed(1)} deg`;
}

function formatUs(value: number | null): string {
  return value === null ? '-' : `${value.toFixed(0)} us`;
}

function formatMaybeNumber(value: number | null, suffix: string, fractionDigits: number): string {
  return value === null ? '-' : `${value.toFixed(fractionDigits)}${suffix}`;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}
