'use client';

import useSWR from 'swr';
import { Camera, Database, RotateCcw, SatelliteDish } from 'lucide-react';
import { useEffect } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { SidebarTrigger } from '@/components/ui/sidebar';
import {
  acquisitionPath,
  type AcquisitionDevices,
  type AcquisitionHealth,
} from '@/lib/acquisition-client';
import { fetcher } from '@/lib/api-client';
import type { ConnectionStatus } from '@/lib/device-manager';
import { useConnectionStore } from '@/store/connection';

import { ThemeToggle } from './theme-toggle';

export function ConnectionBar(): React.ReactElement {
  const { setStatus } = useConnectionStore();
  const { data: connection, mutate: refreshConnection } = useSWR<ConnectionStatus>(
    '/api/connection',
    fetcher,
    { refreshInterval: 5_000 },
  );
  const { data: health, mutate: refreshHealth } = useSWR<AcquisitionHealth>(
    acquisitionPath('/health'),
    fetcher,
    { refreshInterval: 5_000 },
  );
  const { data: devices, mutate: refreshDevices } = useSWR<AcquisitionDevices>(
    acquisitionPath('/devices'),
    fetcher,
    { refreshInterval: 5_000 },
  );

  useEffect(() => {
    if (connection) setStatus(connection);
  }, [connection, setStatus]);

  const refresh = async (): Promise<void> => {
    await Promise.all([refreshConnection(), refreshHealth(), refreshDevices()]);
  };

  const serviceReady = health?.ok === true;
  const serviceLabel = health ? (serviceReady ? '采集服务在线' : '采集服务离线') : '采集服务检测中';

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <SidebarTrigger />
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
        <Badge variant={serviceReady ? 'default' : 'secondary'} className="shrink-0 gap-1">
          <SatelliteDish className="h-3 w-3" />
          {serviceLabel}
        </Badge>
        <DeviceBadge icon={<Database className="h-3 w-3" />} label="H1" status={devices?.h1?.status} />
        <DeviceBadge icon={<Camera className="h-3 w-3" />} label="D455" status={devices?.d455?.status} />
        <DeviceBadge icon={<Camera className="h-3 w-3" />} label="RGB" status={devices?.main_rgb?.status} missingLabel="待接入" />
        <span className="truncate text-xs text-muted-foreground">
          {serviceReady ? (health.mock ? 'mock' : 'hardware') : 'waiting'} · H1{' '}
          {devices?.h1?.serial_number ?? connection?.serialNumber ?? '-'} · D455 {devices?.d455?.serial ?? '-'}
        </span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="icon" aria-label="刷新设备状态" onClick={() => void refresh()}>
          <RotateCcw className="h-4 w-4" />
        </Button>
        <ThemeToggle />
      </div>
    </header>
  );
}

function DeviceBadge({
  icon,
  label,
  status,
  missingLabel = '未发现',
}: {
  icon: React.ReactNode;
  label: string;
  status?: string;
  missingLabel?: string;
}): React.ReactElement {
  const ready = status === 'ready';
  const text = ready ? '已连接' : deviceStatusLabel(status, missingLabel);
  return (
    <Badge variant={ready ? 'default' : 'secondary'} className="shrink-0 gap-1">
      {icon}
      {label} {text}
    </Badge>
  );
}

function deviceStatusLabel(status: string | undefined, missingLabel: string): string {
  if (!status) return '检测中';
  if (status === 'missing') return missingLabel;
  if (status === 'disabled') return '已禁用';
  if (status === 'error') return '异常';
  return status;
}
