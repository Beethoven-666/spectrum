'use client';

import useSWR from 'swr';
import {
  Camera,
  Database,
  Download,
  Eye,
  HardDrive,
  Loader2,
  RefreshCw,
  SatelliteDish,
  Save,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { D455AttitudeIndicator } from '@/components/acquisition/d455-attitude-indicator';
import { SamplePreviewSheet } from '@/components/acquisition/sample-preview-sheet';
import { SpectrometerLivePanel } from '@/components/acquisition/spectrometer-live-panel';
import {
  acquisitionPath,
  type AcquisitionConfig,
  type AcquisitionDevices,
  type AcquisitionHealth,
  type AcquisitionSample,
  type CalibrationSaveResponse,
  type CalibrationStatus,
  type CameraHealth,
  type CaptureResponse,
  type CaptureStatePayload,
  type D455ImuPayload,
  type ExposureMode,
  type ExportResponse,
  type RoiConfig,
  type SamplesResponse,
  type SaveConfigResponse,
  type StorageStatus,
} from '@/lib/acquisition-client';
import { ApiCallError, apiSend, fetcher } from '@/lib/api-client';

const REFRESH_MS = 5000;

type ConfigDraft = {
  colorWidth: string;
  colorHeight: string;
  colorFps: string;
  depthWidth: string;
  depthHeight: string;
  depthFps: string;
  h1Port: string;
  h1Mode: ExposureMode;
  maxAttempts: string;
  initialExposureUs: string;
  minExposureUs: string;
  maxExposureUs: string;
  underMultiplier: string;
  overMultiplier: string;
  multiExposureSteps: string;
  minDepthValidRatio: string;
  distanceMinMm: string;
  distanceMaxMm: string;
  warnAngleDeg: string;
  badAngleDeg: string;
  maxImuDeltaDeg: string;
  warnFreeBytes: string;
  stopFreeBytes: string;
  allowBelowStop: boolean;
};

export default function AcquisitionPage(): React.ReactElement {
  const [capturing, setCapturing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [savingCalibration, setSavingCalibration] = useState(false);
  const [previewVersion, setPreviewVersion] = useState(0);
  const [documentVisible, setDocumentVisible] = useState(true);
  const [selectedSampleId, setSelectedSampleId] = useState<string | null>(null);
  const [exportQuality, setExportQuality] = useState<'all' | 'good' | 'warn' | 'bad'>('all');
  const [roiDraft, setRoiDraft] = useState<RoiDraft>({
    x: '0.35',
    y: '0.35',
    width: '0.30',
    height: '0.30',
  });
  const [exposureMode, setExposureMode] = useState<ExposureMode>('conservative');
  const [configDraft, setConfigDraft] = useState<ConfigDraft | null>(null);
  const [calibrationJson, setCalibrationJson] = useState('{\n  "version": "manual"\n}');
  const [captureState, setCaptureState] = useState<CaptureStatePayload>({
    state: 'idle',
    sample_id: null,
    error: null,
  });

  const { data: health, error: healthError, mutate: refreshHealth } = useSWR<AcquisitionHealth>(
    acquisitionPath('/health'),
    fetcher,
    { refreshInterval: REFRESH_MS },
  );
  const { data: devices, mutate: refreshDevices } = useSWR<AcquisitionDevices>(
    acquisitionPath('/devices'),
    fetcher,
    { refreshInterval: REFRESH_MS },
  );
  const { data: storage, mutate: refreshStorage } = useSWR<StorageStatus>(
    acquisitionPath('/storage'),
    fetcher,
    { refreshInterval: REFRESH_MS },
  );
  const { data: samples, mutate: refreshSamples } = useSWR<SamplesResponse>(
    acquisitionPath('/samples?limit=12'),
    fetcher,
    { refreshInterval: REFRESH_MS },
  );
  const { data: config, mutate: refreshConfig } = useSWR<AcquisitionConfig>(
    acquisitionPath('/config'),
    fetcher,
  );
  const { data: calibration, mutate: refreshCalibration } = useSWR<CalibrationStatus>(
    acquisitionPath('/calibration'),
    fetcher,
  );
  // Pause all preview polling while a capture is running (give the USB bus to
  // the sample) and while the tab is hidden (let demand decay so the cameras
  // idle-close and release the bus).
  const captureInProgress =
    capturing ||
    captureState.state === 'capture_requested' ||
    captureState.state === 'capturing' ||
    captureState.state === 'writing';
  const previewsActive = health?.ok === true && !captureInProgress && documentVisible;

  const { data: d455Imu } = useSWR<D455ImuPayload>(
    health?.ok ? acquisitionPath('/preview/d455/imu') : null,
    fetcher,
    { refreshInterval: previewsActive ? REFRESH_MS : 0 },
  );

  useEffect(() => {
    const onVisibility = (): void => setDocumentVisible(document.visibilityState === 'visible');
    onVisibility();
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  useEffect(() => {
    if (!previewsActive) return;
    const timer = setInterval(() => {
      setPreviewVersion((current) => current + 1);
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [previewsActive]);

  useEffect(() => {
    // Capture-state stream. The native EventSource auto-reconnects (~3s) after
    // every transport drop and would otherwise pin a sticky "disconnected"
    // error forever, so we close it ourselves after a few drops and reconnect
    // with bounded backoff instead of letting the browser storm.
    const MAX_DROPS = 5;
    const BACKOFF_MAX_MS = 8000;
    let es: EventSource | null = null;
    let closed = false;
    let drops = 0;
    let backoffTimer: ReturnType<typeof setTimeout> | null = null;

    const open = (): void => {
      if (closed) return;
      es = new EventSource(acquisitionPath('/events'));
      es.addEventListener('state', (event) => {
        drops = 0;
        try {
          setCaptureState(JSON.parse((event as MessageEvent).data) as CaptureStatePayload);
        } catch {
          setCaptureState({ state: 'error', error: 'invalid event payload' });
        }
      });
      es.onerror = () => {
        if (closed) return;
        // Suppress the native auto-reconnect; back off and retry a bounded
        // number of times before giving up so we never reconnect-storm.
        es?.close();
        es = null;
        drops += 1;
        if (drops >= MAX_DROPS) {
          setCaptureState((current) => ({ ...current, error: 'event stream disconnected' }));
          return;
        }
        const delay = Math.min(1000 * 2 ** (drops - 1), BACKOFF_MAX_MS);
        backoffTimer = setTimeout(open, delay);
      };
    };

    open();
    return () => {
      closed = true;
      if (backoffTimer) clearTimeout(backoffTimer);
      es?.close();
    };
  }, []);

  const previewUrl = useMemo(
    () => `${acquisitionPath('/preview/d455/frame')}?v=${previewVersion}`,
    [previewVersion],
  );
  const depthPreviewUrl = useMemo(
    () => `${acquisitionPath('/preview/d455/depth')}?v=${previewVersion}`,
    [previewVersion],
  );
  const activeConfigDraft = configDraft ?? (config ? configToDraft(config) : null);

  const refreshAll = async (): Promise<void> => {
    await Promise.all([
      refreshHealth(),
      refreshDevices(),
      refreshStorage(),
      refreshSamples(),
      refreshConfig(),
      refreshCalibration(),
    ]);
    setPreviewVersion((current) => current + 1);
  };

  const capture = async (): Promise<void> => {
    setCapturing(true);
    try {
      const result = await apiSend<CaptureResponse>(acquisitionPath('/capture'), 'POST', {
        exposure_mode: exposureMode,
        roi: roiFromDraft(roiDraft),
      });
      toast.success(`样本已保存：${result.sample_id}`);
      await refreshAll();
    } catch (err) {
      toast.error(`采集失败：${errorMessage(err)}`);
    } finally {
      setCapturing(false);
    }
  };

  const exportAll = async (): Promise<void> => {
    setExporting(true);
    try {
      const result = await apiSend<ExportResponse>(
        acquisitionPath('/samples/export'),
        'POST',
        exportQuality === 'all' ? undefined : { quality_status: exportQuality },
      );
      toast.success(`导出已生成：${result.filename}`);
      await refreshStorage();
    } catch (err) {
      toast.error(`导出失败：${errorMessage(err)}`);
    } finally {
      setExporting(false);
    }
  };

  const saveConfig = async (): Promise<void> => {
    if (!activeConfigDraft) return;
    setSavingConfig(true);
    try {
      const result = await apiSend<SaveConfigResponse>(acquisitionPath('/config'), 'PUT', draftToConfig(activeConfigDraft));
      setConfigDraft(configToDraft(result.config));
      await refreshConfig(result.config);
      toast.success(result.restart_required ? '配置已保存，硬件 profile 重启后生效' : '配置已保存');
    } catch (err) {
      toast.error(`配置保存失败：${errorMessage(err)}`);
    } finally {
      setSavingConfig(false);
    }
  };

  const saveCalibration = async (): Promise<void> => {
    setSavingCalibration(true);
    try {
      const payload = JSON.parse(calibrationJson) as Record<string, unknown>;
      const result = await apiSend<CalibrationSaveResponse>(acquisitionPath('/calibration'), 'PUT', payload);
      toast.success(`标定已保存：${result.version}`);
      await Promise.all([refreshCalibration(), refreshConfig()]);
    } catch (err) {
      toast.error(`标定保存失败：${errorMessage(err)}`);
    } finally {
      setSavingCalibration(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">多模态采集</h1>
          <p className="text-sm text-muted-foreground">D455 + H1 叶片样本</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void refreshAll()}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
          <Button onClick={() => void capture()} disabled={!health?.ok || capturing}>
            {capturing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
            采集样本
          </Button>
        </div>
      </div>

      {healthError ? (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle className="text-base text-destructive">采集服务不可达</CardTitle>
          </CardHeader>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-5">
        <StatusCard
          icon={<SatelliteDish className="h-4 w-4" />}
          label="服务"
          value={health?.ok ? `online · ${health.mock ? 'mock' : 'hardware'}` : 'offline'}
          status={health?.ok ? 'good' : 'bad'}
        />
        <StatusCard
          icon={<Camera className="h-4 w-4" />}
          label="D455"
          value={devices?.d455?.serial ?? devices?.d455?.name ?? '-'}
          status={statusToQuality(devices?.d455?.status)}
        />
        <StatusCard
          icon={<Database className="h-4 w-4" />}
          label="H1"
          value={devices?.h1?.serial_number ?? devices?.h1?.serial ?? '-'}
          status={statusToQuality(devices?.h1?.status)}
        />
        <StatusCard
          icon={<HardDrive className="h-4 w-4" />}
          label="剩余空间"
          value={storage ? formatBytes(storage.free_bytes) : '-'}
          status={storage?.status ?? 'warn'}
        />
        <StatusCard
          icon={<Database className="h-4 w-4" />}
          label="采集状态"
          value={captureState.state}
          status={captureState.error ? 'bad' : captureState.state === 'failed' ? 'bad' : captureState.state === 'done' ? 'good' : 'warn'}
        />
      </div>

      <Tabs defaultValue="capture">
        <TabsList className="grid w-full grid-cols-4 md:w-fit">
          <TabsTrigger value="capture">采集</TabsTrigger>
          <TabsTrigger value="samples">样本</TabsTrigger>
          <TabsTrigger value="settings">设置</TabsTrigger>
          <TabsTrigger value="calibration">标定</TabsTrigger>
        </TabsList>

        <TabsContent value="capture" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">D455 RGB / Depth / IMU</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {health?.ok ? (
                  <>
                    <div className="grid gap-3 md:grid-cols-2">
                      <PreviewImage src={previewUrl} alt="D455 RGB preview" label="RGB" />
                      <PreviewImage src={depthPreviewUrl} alt="D455 depth preview" label="Depth" />
                    </div>
                    <D455AttitudeIndicator
                      imu={d455Imu}
                      maxDeltaDeg={config?.quality.max_imu_delta_deg ?? 8}
                    />
                  </>
                ) : (
                  <div className="flex aspect-video items-center justify-center rounded-md border bg-muted text-sm text-muted-foreground">
                    等待采集服务
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">设备状态</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <DeviceRow name="H1 光谱仪" status={devices?.h1?.status} detail={devices?.h1?.wavelength_range ? `${devices.h1.wavelength_range.start}-${devices.h1.wavelength_range.end} nm` : devices?.h1?.detail?.error} />
                <DeviceRow name="RealSense D455" status={devices?.d455?.status} detail={devices?.d455?.serial ?? devices?.d455?.name} health={devices?.d455?.health} />
                <DeviceRow name="主 RGB" status={devices?.main_rgb?.status} detail={mainRgbDetail(devices?.main_rgb)} health={devices?.main_rgb?.health} />
                <Separator />
                <div className="space-y-1 text-sm">
                  <KeyValue label="数据目录" value={storage?.data_dir ?? '-'} />
                  <KeyValue label="已用 / 总量" value={storage ? `${formatBytes(storage.used_bytes)} / ${formatBytes(storage.total_bytes)}` : '-'} />
                  <KeyValue label="标定版本" value={calibration?.version ?? calibration?.status ?? '-'} />
                  <KeyValue label="当前样本" value={captureState.sample_id ?? '-'} />
                  <KeyValue label="失败原因" value={captureState.error ?? '-'} />
                </div>
              </CardContent>
            </Card>
          </div>

          <SpectrometerLivePanel
            serviceOk={health?.ok === true}
            h1Ready={devices?.h1?.status === 'ready'}
            mainRgbStatus={devices?.main_rgb?.status}
            mainRgbDetail={mainRgbDetail(devices?.main_rgb)}
            previewVersion={previewVersion}
            disabled={captureInProgress}
          />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">采集参数</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-[160px_repeat(4,1fr)_auto] md:items-end">
              <div className="space-y-2">
                <Label>曝光策略</Label>
                <Select value={exposureMode} onValueChange={(value) => setExposureMode(value as ExposureMode)}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="conservative">conservative</SelectItem>
                    <SelectItem value="strict">strict</SelectItem>
                    <SelectItem value="multi_exposure">multi exposure</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <NumberField label="ROI X" value={roiDraft.x} onChange={(value) => setRoiDraft({ ...roiDraft, x: value })} step="0.01" />
              <NumberField label="ROI Y" value={roiDraft.y} onChange={(value) => setRoiDraft({ ...roiDraft, y: value })} step="0.01" />
              <NumberField label="ROI W" value={roiDraft.width} onChange={(value) => setRoiDraft({ ...roiDraft, width: value })} step="0.01" />
              <NumberField label="ROI H" value={roiDraft.height} onChange={(value) => setRoiDraft({ ...roiDraft, height: value })} step="0.01" />
              <Button onClick={() => void capture()} disabled={!health?.ok || capturing}>
                {capturing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
                采集
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="samples">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
              <CardTitle className="text-base">样本列表</CardTitle>
              <div className="flex gap-2">
                <Select value={exportQuality} onValueChange={(value) => setExportQuality(value as typeof exportQuality)}>
                  <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">all</SelectItem>
                    <SelectItem value="good">good</SelectItem>
                    <SelectItem value="warn">warn</SelectItem>
                    <SelectItem value="bad">bad</SelectItem>
                  </SelectContent>
                </Select>
                <Button variant="outline" onClick={() => void exportAll()} disabled={exporting}>
                  {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                  批量导出
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="divide-y rounded-md border">
                {(samples?.samples ?? []).length === 0 ? (
                  <div className="p-6 text-center text-sm text-muted-foreground">还没有样本</div>
                ) : (
                  samples?.samples.map((sample) => (
                    <SampleRow key={sample.id} sample={sample} onPreview={setSelectedSampleId} />
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="settings" className="space-y-4">
          {activeConfigDraft ? (
            <>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">D455 Profile</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-3">
                  <NumberField label="Color width" value={activeConfigDraft.colorWidth} onChange={(value) => setConfigDraft({ ...activeConfigDraft, colorWidth: value })} />
                  <NumberField label="Color height" value={activeConfigDraft.colorHeight} onChange={(value) => setConfigDraft({ ...activeConfigDraft, colorHeight: value })} />
                  <NumberField label="Color fps" value={activeConfigDraft.colorFps} onChange={(value) => setConfigDraft({ ...activeConfigDraft, colorFps: value })} />
                  <NumberField label="Depth width" value={activeConfigDraft.depthWidth} onChange={(value) => setConfigDraft({ ...activeConfigDraft, depthWidth: value })} />
                  <NumberField label="Depth height" value={activeConfigDraft.depthHeight} onChange={(value) => setConfigDraft({ ...activeConfigDraft, depthHeight: value })} />
                  <NumberField label="Depth fps" value={activeConfigDraft.depthFps} onChange={(value) => setConfigDraft({ ...activeConfigDraft, depthFps: value })} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">H1 自动曝光</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label>默认策略</Label>
                    <Select value={activeConfigDraft.h1Mode} onValueChange={(value) => setConfigDraft({ ...activeConfigDraft, h1Mode: value as ExposureMode })}>
                      <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="conservative">conservative</SelectItem>
                        <SelectItem value="strict">strict</SelectItem>
                        <SelectItem value="multi_exposure">multi exposure</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <TextField label="H1 port" value={activeConfigDraft.h1Port} onChange={(value) => setConfigDraft({ ...activeConfigDraft, h1Port: value })} />
                  <NumberField label="Max attempts" value={activeConfigDraft.maxAttempts} onChange={(value) => setConfigDraft({ ...activeConfigDraft, maxAttempts: value })} />
                  <NumberField label="Initial exposure us" value={activeConfigDraft.initialExposureUs} onChange={(value) => setConfigDraft({ ...activeConfigDraft, initialExposureUs: value })} />
                  <NumberField label="Min exposure us" value={activeConfigDraft.minExposureUs} onChange={(value) => setConfigDraft({ ...activeConfigDraft, minExposureUs: value })} />
                  <NumberField label="Max exposure us" value={activeConfigDraft.maxExposureUs} onChange={(value) => setConfigDraft({ ...activeConfigDraft, maxExposureUs: value })} />
                  <NumberField label="Under multiplier" value={activeConfigDraft.underMultiplier} onChange={(value) => setConfigDraft({ ...activeConfigDraft, underMultiplier: value })} step="0.1" />
                  <NumberField label="Over multiplier" value={activeConfigDraft.overMultiplier} onChange={(value) => setConfigDraft({ ...activeConfigDraft, overMultiplier: value })} step="0.1" />
                  <NumberField label="Multi-exposure steps" value={activeConfigDraft.multiExposureSteps} onChange={(value) => setConfigDraft({ ...activeConfigDraft, multiExposureSteps: value })} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">质量和空间阈值</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-3">
                  <NumberField label="Min depth ratio" value={activeConfigDraft.minDepthValidRatio} onChange={(value) => setConfigDraft({ ...activeConfigDraft, minDepthValidRatio: value })} step="0.01" />
                  <NumberField label="Distance min mm" value={activeConfigDraft.distanceMinMm} onChange={(value) => setConfigDraft({ ...activeConfigDraft, distanceMinMm: value })} />
                  <NumberField label="Distance max mm" value={activeConfigDraft.distanceMaxMm} onChange={(value) => setConfigDraft({ ...activeConfigDraft, distanceMaxMm: value })} />
                  <NumberField label="Warn angle deg" value={activeConfigDraft.warnAngleDeg} onChange={(value) => setConfigDraft({ ...activeConfigDraft, warnAngleDeg: value })} />
                  <NumberField label="Bad angle deg" value={activeConfigDraft.badAngleDeg} onChange={(value) => setConfigDraft({ ...activeConfigDraft, badAngleDeg: value })} />
                  <NumberField label="Max IMU delta deg" value={activeConfigDraft.maxImuDeltaDeg} onChange={(value) => setConfigDraft({ ...activeConfigDraft, maxImuDeltaDeg: value })} />
                  <NumberField label="Warn free bytes" value={activeConfigDraft.warnFreeBytes} onChange={(value) => setConfigDraft({ ...activeConfigDraft, warnFreeBytes: value })} />
                  <NumberField label="Stop free bytes" value={activeConfigDraft.stopFreeBytes} onChange={(value) => setConfigDraft({ ...activeConfigDraft, stopFreeBytes: value })} />
                  <div className="flex items-end justify-between gap-3 rounded-md border px-3 py-2">
                    <Label>Allow below stop</Label>
                    <Switch checked={activeConfigDraft.allowBelowStop} onCheckedChange={(checked) => setConfigDraft({ ...activeConfigDraft, allowBelowStop: checked })} />
                  </div>
                </CardContent>
              </Card>
              <div className="flex justify-end">
                <Button onClick={() => void saveConfig()} disabled={savingConfig}>
                  {savingConfig ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存设置
                </Button>
              </div>
            </>
          ) : (
            <Card><CardContent className="p-6 text-sm text-muted-foreground">等待配置</CardContent></Card>
          )}
        </TabsContent>

        <TabsContent value="calibration" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">当前标定</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm md:grid-cols-3">
              <KeyValue label="状态" value={calibration?.status ?? '-'} />
              <KeyValue label="版本" value={calibration?.version ?? '-'} />
              <KeyValue label="路径" value={calibration?.path ?? '-'} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">保存 calibration.json</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Textarea
                className="min-h-64 font-mono text-xs"
                value={calibrationJson}
                onChange={(event) => setCalibrationJson(event.target.value)}
              />
              <div className="flex justify-end">
                <Button onClick={() => void saveCalibration()} disabled={savingCalibration}>
                  {savingCalibration ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存标定
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
      <SamplePreviewSheet
        sampleId={selectedSampleId}
        open={selectedSampleId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedSampleId(null);
        }}
      />
    </div>
  );
}

type RoiDraft = {
  x: string;
  y: string;
  width: string;
  height: string;
};

function StatusCard({
  icon,
  label,
  value,
  status,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  status: 'good' | 'warn' | 'bad';
}): React.ReactElement {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <span className="text-muted-foreground">{icon}</span>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="truncate text-lg font-semibold">{value}</div>
        <QualityBadge status={status} />
      </CardContent>
    </Card>
  );
}

function DeviceRow({
  name,
  status,
  detail,
  health,
}: {
  name: string;
  status?: string;
  detail?: unknown;
  health?: CameraHealth;
}): React.ReactElement {
  const reconnecting = health?.reconnecting === true;
  const detailText = reconnecting && health?.last_error ? health.last_error : detail ? String(detail) : '-';
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="text-sm font-medium">{name}</div>
        <div className="truncate text-xs text-muted-foreground">{detailText}</div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {reconnecting ? <Badge variant="secondary">重连中</Badge> : null}
        <QualityBadge status={statusToQuality(status)} />
      </div>
    </div>
  );
}

function SampleRow({
  sample,
  onPreview,
}: {
  sample: AcquisitionSample;
  onPreview: (sampleId: string) => void;
}): React.ReactElement {
  return (
    <div className="grid gap-3 p-3 text-sm md:grid-cols-[84px_minmax(0,1fr)_90px_90px_90px_110px_auto] md:items-center">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={acquisitionPath(`/samples/${sample.id}/preview`)}
        alt={`${sample.id} ROI preview`}
        className="aspect-video w-20 rounded border object-cover"
      />
      <div className="min-w-0">
        <div className="truncate font-mono text-xs">{sample.id}</div>
        <div className="text-xs text-muted-foreground">{new Date(sample.created_at).toLocaleString()}</div>
        {sample.warnings.length > 0 ? (
          <div className="truncate text-xs text-muted-foreground">{sample.warnings.join(', ')}</div>
        ) : null}
      </div>
      <QualityBadge status={sample.quality_status} />
      <Metric label="距离" value={sample.distance_mm === null ? '-' : `${sample.distance_mm.toFixed(0)} mm`} />
      <Metric label="角度" value={sample.angle_deg === null ? '-' : `${sample.angle_deg.toFixed(1)} deg`} />
      <Metric label="曝光" value={sample.h1_exposure_status ?? '-'} />
      <div className="flex flex-wrap gap-2 md:justify-end">
        <Button variant="outline" size="sm" onClick={() => onPreview(sample.id)}>
          <Eye className="h-4 w-4" />
          预览
        </Button>
        <a
          href={acquisitionPath(`/samples/${sample.id}/download`)}
          className={buttonVariants({ variant: 'outline', size: 'sm' })}
        >
          <Download className="h-4 w-4" />
          下载
        </a>
      </div>
    </div>
  );
}

function PreviewImage({
  src,
  alt,
  label,
}: {
  src: string;
  alt: string;
  label: string;
}): React.ReactElement {
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} className="aspect-video w-full rounded-md border object-cover" />
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step = '1',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  step?: string;
}): React.ReactElement {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Input type="number" step={step} value={value} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}): React.ReactElement {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Input value={value} onChange={(event) => onChange(event.target.value)} />
    </div>
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

function Metric({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div>
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
      <div className="font-mono text-xs">{value}</div>
    </div>
  );
}

function QualityBadge({ status }: { status: 'good' | 'warn' | 'bad' }): React.ReactElement {
  const variant = status === 'good' ? 'default' : status === 'warn' ? 'secondary' : 'destructive';
  return <Badge variant={variant}>{status}</Badge>;
}

function statusToQuality(status?: string): 'good' | 'warn' | 'bad' {
  if (status === 'ready' || status === 'good') return 'good';
  if (status === 'missing' || status === 'disabled' || status === 'warn') return 'warn';
  return 'bad';
}

function mainRgbDetail(device?: AcquisitionDevices['main_rgb']): string {
  if (!device) return '-';
  if (device.status === 'ready') return device.serial ?? device.name ?? '已连接';
  const detail = device.detail;
  if (detail && typeof detail === 'object') {
    const reason = 'reason' in detail ? detail.reason : 'error' in detail ? detail.error : null;
    if (typeof reason === 'string' && reason.length > 0) return reason;
  }
  return device.status === 'missing' ? '待接入' : String(device.status);
}

function roiFromDraft(roi: RoiDraft): RoiConfig {
  return {
    x: numberValue(roi.x, 0.35),
    y: numberValue(roi.y, 0.35),
    width: numberValue(roi.width, 0.3),
    height: numberValue(roi.height, 0.3),
    source: 'manual',
  };
}

function configToDraft(config: AcquisitionConfig): ConfigDraft {
  return {
    colorWidth: String(config.d455_profile.color_width),
    colorHeight: String(config.d455_profile.color_height),
    colorFps: String(config.d455_profile.color_fps),
    depthWidth: String(config.d455_profile.depth_width),
    depthHeight: String(config.d455_profile.depth_height),
    depthFps: String(config.d455_profile.depth_fps),
    h1Port: config.h1_port,
    h1Mode: config.h1_auto_exposure.mode,
    maxAttempts: String(config.h1_auto_exposure.max_attempts),
    initialExposureUs: String(config.h1_auto_exposure.initial_exposure_us),
    minExposureUs: String(config.h1_auto_exposure.min_exposure_us),
    maxExposureUs: String(config.h1_auto_exposure.max_exposure_us),
    underMultiplier: String(config.h1_auto_exposure.under_multiplier),
    overMultiplier: String(config.h1_auto_exposure.over_multiplier),
    multiExposureSteps: String(config.h1_auto_exposure.multi_exposure_steps),
    minDepthValidRatio: String(config.quality.min_depth_valid_ratio),
    distanceMinMm: String(config.quality.recommended_distance_min_mm),
    distanceMaxMm: String(config.quality.recommended_distance_max_mm),
    warnAngleDeg: String(config.quality.warn_angle_deg),
    badAngleDeg: String(config.quality.bad_angle_deg),
    maxImuDeltaDeg: String(config.quality.max_imu_delta_deg),
    warnFreeBytes: String(config.disk.warn_free_bytes),
    stopFreeBytes: String(config.disk.stop_free_bytes),
    allowBelowStop: config.disk.allow_below_stop,
  };
}

function draftToConfig(draft: ConfigDraft): Partial<AcquisitionConfig> {
  return {
    h1_port: draft.h1Port,
    d455_profile: {
      color_width: intValue(draft.colorWidth, 640),
      color_height: intValue(draft.colorHeight, 480),
      color_fps: intValue(draft.colorFps, 15),
      depth_width: intValue(draft.depthWidth, 640),
      depth_height: intValue(draft.depthHeight, 480),
      depth_fps: intValue(draft.depthFps, 15),
    },
    h1_auto_exposure: {
      mode: draft.h1Mode,
      max_attempts: intValue(draft.maxAttempts, 4),
      initial_exposure_us: intValue(draft.initialExposureUs, 50000),
      min_exposure_us: intValue(draft.minExposureUs, 500),
      max_exposure_us: intValue(draft.maxExposureUs, 5000000),
      under_multiplier: numberValue(draft.underMultiplier, 1.7),
      over_multiplier: numberValue(draft.overMultiplier, 0.55),
      multi_exposure_steps: intValue(draft.multiExposureSteps, 5),
    },
    quality: {
      min_depth_valid_ratio: numberValue(draft.minDepthValidRatio, 0.5),
      recommended_distance_min_mm: numberValue(draft.distanceMinMm, 180),
      recommended_distance_max_mm: numberValue(draft.distanceMaxMm, 800),
      warn_angle_deg: numberValue(draft.warnAngleDeg, 45),
      bad_angle_deg: numberValue(draft.badAngleDeg, 70),
      max_imu_delta_deg: numberValue(draft.maxImuDeltaDeg, 8),
    },
    disk: {
      warn_free_bytes: intValue(draft.warnFreeBytes, 2 * 1024 * 1024 * 1024),
      stop_free_bytes: intValue(draft.stopFreeBytes, 1024 * 1024 * 1024),
      allow_below_stop: draft.allowBelowStop,
    },
  };
}

function intValue(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function numberValue(value: string, fallback: number): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
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

function errorMessage(err: unknown): string {
  return err instanceof ApiCallError ? err.message : String(err);
}
