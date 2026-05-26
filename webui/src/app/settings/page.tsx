'use client';

import useSWR from 'swr';
import { Loader2, Moon, Sun } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

import { ApiCallError, apiSend, fetcher } from '@/lib/api-client';
import { useConnectionStore } from '@/store/connection';

interface ExposureState {
  mode: 'auto' | 'manual';
  timeUs: number;
  maxTimeUs: number;
}

interface CieState { mode: string }

const CIE_OPTIONS = [
  { value: 'cie1931_2', label: 'CIE 1931 2°' },
  { value: 'cie1964_10', label: 'CIE 1964 10°' },
  { value: 'cie2015_2', label: 'CIE 2015 2°' },
  { value: 'cie2015_10', label: 'CIE 2015 10°' },
];

export default function SettingsPage(): React.ReactElement {
  const connected = useConnectionStore((s) => s.status.connected);
  const { data: exposure, mutate: mutateExposure } = useSWR<ExposureState>(
    connected ? '/api/device/exposure' : null,
    fetcher,
  );
  const { data: cie, mutate: mutateCie } = useSWR<CieState>(
    connected ? '/api/device/cie-mode' : null,
    fetcher,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">设备设置</h1>
        <p className="text-sm text-muted-foreground">
          调整曝光参数、CIE 模式、工作模式与睡眠开关。
        </p>
      </div>

      <ExposureCard
        key={exposure ? `${exposure.mode}-${exposure.timeUs}-${exposure.maxTimeUs}` : 'empty'}
        state={exposure}
        onUpdated={(s) => void mutateExposure(s)}
        disabled={!connected}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">CIE 颜色匹配函数</CardTitle>
          <CardDescription>切换 CIE 标准观察者 / 视场。</CardDescription>
        </CardHeader>
        <CardContent>
          <Select
            disabled={!connected || !cie}
            value={cie?.mode ?? 'cie1931_2'}
            onValueChange={async (v) => {
              try {
                const next = await apiSend<CieState>('/api/device/cie-mode', 'PUT', { mode: v });
                await mutateCie(next);
                toast.success('CIE 模式已更新');
              } catch (err) {
                const msg = err instanceof ApiCallError ? err.message : String(err);
                toast.error(`更新失败：${msg}`);
              }
            }}
          >
            <SelectTrigger className="w-72"><SelectValue placeholder="选择" /></SelectTrigger>
            <SelectContent>
              {CIE_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <WorkingModeCard disabled={!connected} />
      <SleepCard disabled={!connected} />
    </div>
  );
}

function ExposureCard({
  state,
  onUpdated,
  disabled,
}: {
  state: ExposureState | undefined;
  onUpdated: (s: ExposureState) => void;
  disabled: boolean;
}): React.ReactElement {
  // Mounted with state from the parent via `key`; if the parent re-fetches a
  // new exposure tuple it remounts this card to reset the form.
  const [mode, setMode] = useState<'auto' | 'manual'>(state?.mode ?? 'auto');
  const [timeUs, setTimeUs] = useState<string>(state?.timeUs.toString() ?? '');
  const [maxUs, setMaxUs] = useState<string>(state?.maxTimeUs.toString() ?? '');
  const [busy, setBusy] = useState(false);

  const submit = async (): Promise<void> => {
    setBusy(true);
    try {
      const next = await apiSend<ExposureState>('/api/device/exposure', 'PATCH', {
        mode,
        timeUs: Number(timeUs),
        maxTimeUs: Number(maxUs),
      });
      onUpdated(next);
      toast.success('曝光参数已更新');
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`更新失败：${msg}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">曝光控制</CardTitle>
        <CardDescription>手动模式下时间生效；自动模式由设备根据 max 时间寻优。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-3">
        <div className="space-y-2">
          <Label>模式</Label>
          <Select value={mode} onValueChange={(v) => setMode(v as 'auto' | 'manual')} disabled={disabled || busy}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">自动</SelectItem>
              <SelectItem value="manual">手动</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="exp-time">曝光时间 (µs)</Label>
          <Input
            id="exp-time"
            type="number"
            min={0}
            value={timeUs}
            onChange={(e) => setTimeUs(e.target.value)}
            disabled={disabled || busy}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="exp-max">最大曝光时间 (µs)</Label>
          <Input
            id="exp-max"
            type="number"
            min={0}
            value={maxUs}
            onChange={(e) => setMaxUs(e.target.value)}
            disabled={disabled || busy}
          />
        </div>
        <div className="md:col-span-3">
          <Button onClick={() => void submit()} disabled={disabled || busy}>
            {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            保存
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function WorkingModeCard({ disabled }: { disabled: boolean }): React.ReactElement {
  const [busy, setBusy] = useState(false);
  const set = async (mode: 'streaming' | 'trigger'): Promise<void> => {
    setBusy(true);
    try {
      await apiSend('/api/device/working-mode', 'PUT', { mode });
      toast.success(`已设置为 ${mode === 'trigger' ? 'Trigger' : 'Streaming'} 模式`);
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`更新失败：${msg}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">工作模式</CardTitle>
        <CardDescription>
          Trigger 模式下曝光时间须为手动且在 7–59ms 范围。
        </CardDescription>
      </CardHeader>
      <CardContent className="flex gap-2">
        <Button variant="outline" disabled={disabled || busy} onClick={() => void set('streaming')}>
          Streaming
        </Button>
        <Button variant="outline" disabled={disabled || busy} onClick={() => void set('trigger')}>
          Trigger
        </Button>
      </CardContent>
    </Card>
  );
}

function SleepCard({ disabled }: { disabled: boolean }): React.ReactElement {
  const [busy, setBusy] = useState(false);
  const send = async (path: '/api/device/sleep' | '/api/device/wake'): Promise<void> => {
    setBusy(true);
    try {
      await apiSend(path, 'POST');
      toast.success(path === '/api/device/sleep' ? '已发送睡眠命令' : '已发送唤醒命令');
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`命令失败：${msg}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">睡眠 / 唤醒</CardTitle>
        <CardDescription>
          设备的 0x40 是开关命令，第一次进入睡眠，第二次唤醒。
        </CardDescription>
      </CardHeader>
      <CardContent className="flex gap-2">
        <Button variant="outline" disabled={disabled || busy} onClick={() => void send('/api/device/sleep')}>
          <Moon className="mr-2 h-4 w-4" /> 睡眠
        </Button>
        <Button variant="outline" disabled={disabled || busy} onClick={() => void send('/api/device/wake')}>
          <Sun className="mr-2 h-4 w-4" /> 唤醒
        </Button>
      </CardContent>
    </Card>
  );
}
