'use client';

import useSWR from 'swr';
import { Plug, PlugZap, RotateCcw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ApiCallError, apiSend, fetcher } from '@/lib/api-client';
import type { ConnectionStatus } from '@/lib/device-manager';
import { useConnectionStore } from '@/store/connection';

import { ThemeToggle } from './theme-toggle';

export function ConnectionBar(): React.ReactElement {
  const { setStatus, status } = useConnectionStore();
  const { data, mutate } = useSWR<ConnectionStatus>('/api/connection', fetcher, {
    refreshInterval: 5_000,
  });
  useEffect(() => {
    if (data) setStatus(data);
  }, [data, setStatus]);

  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<'mock' | 'serial'>('mock');
  const [port, setPort] = useState('/dev/cu.usbserial-XXXX');
  const [pending, setPending] = useState(false);

  const handleConnect = async (): Promise<void> => {
    setPending(true);
    try {
      const next = await apiSend<ConnectionStatus>(
        '/api/connection',
        'POST',
        mode === 'mock' ? { mode: 'mock' } : { mode: 'serial', port },
      );
      setStatus(next);
      await mutate(next);
      toast.success(mode === 'mock' ? '已连接到 Mock 设备' : `已连接 ${port}`);
      setOpen(false);
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`连接失败：${msg}`);
    } finally {
      setPending(false);
    }
  };

  const handleDisconnect = async (): Promise<void> => {
    setPending(true);
    try {
      const next = await apiSend<ConnectionStatus>('/api/connection', 'DELETE');
      setStatus(next);
      await mutate(next);
      toast.success('已断开连接');
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`断开失败：${msg}`);
    } finally {
      setPending(false);
    }
  };

  const connected = status.connected;
  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <SidebarTrigger />
      <div className="flex items-center gap-2">
        <Badge variant={connected ? 'default' : 'secondary'} className="gap-1">
          {connected ? <PlugZap className="h-3 w-3" /> : <Plug className="h-3 w-3" />}
          {connected ? '已连接' : '未连接'}
        </Badge>
        {connected ? (
          <span className="text-xs text-muted-foreground">
            {status.mode === 'mock' ? 'Mock 模式' : '串口'} · {status.port ?? ''}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">点击右侧按钮配置端口</span>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label="刷新状态"
          onClick={() => void mutate()}
        >
          <RotateCcw className="h-4 w-4" />
        </Button>
        {connected ? (
          <Button variant="outline" size="sm" disabled={pending} onClick={() => void handleDisconnect()}>
            断开
          </Button>
        ) : null}
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            render={
              <Button size="sm" disabled={pending}>
                {connected ? '切换连接' : '连接'}
              </Button>
            }
          />
          <SheetContent className="w-full sm:max-w-md">
            <SheetHeader>
              <SheetTitle>连接 H1 光谱仪</SheetTitle>
              <SheetDescription>
                选择 Mock 模拟设备或指定真实串口。Mock 模式不需要任何硬件。
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-4">
              <Tabs value={mode} onValueChange={(v) => setMode(v as 'mock' | 'serial')}>
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="mock">Mock</TabsTrigger>
                  <TabsTrigger value="serial">串口</TabsTrigger>
                </TabsList>
                <TabsContent value="mock" className="mt-3 text-sm text-muted-foreground">
                  使用内置 MockSerialPort，自动响应全部 20 条命令，光谱由 5500K 暖白 LED 合成器实时生成。
                </TabsContent>
                <TabsContent value="serial" className="mt-3 space-y-2">
                  <Label htmlFor="port-path">串口路径</Label>
                  <Input
                    id="port-path"
                    value={port}
                    onChange={(e) => setPort(e.target.value)}
                    placeholder="/dev/cu.usbserial-XXXX 或 COM3"
                  />
                  <p className="text-xs text-muted-foreground">
                    将以 115200 8N1 打开。需要硬件已插入并被系统识别。
                  </p>
                </TabsContent>
              </Tabs>
            </div>
            <SheetFooter>
              <SheetClose render={<Button variant="ghost">取消</Button>} />
              <Button disabled={pending} onClick={() => void handleConnect()}>
                {pending ? '连接中…' : '连接'}
              </Button>
            </SheetFooter>
          </SheetContent>
        </Sheet>
        <ThemeToggle />
      </div>
    </header>
  );
}
