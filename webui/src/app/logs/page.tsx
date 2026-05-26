'use client';

import useSWR from 'swr';
import { Eraser, Pause, Play } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ApiCallError, apiSend, fetcher } from '@/lib/api-client';
import type { LogEntry, LogSnapshot } from '@/lib/log-capture';
import { timestamp } from '@/lib/format';

export default function LogsPage(): React.ReactElement {
  const { data, mutate } = useSWR<LogSnapshot>('/api/logs', fetcher, { refreshInterval: 500 });
  const [paused, setPaused] = useState(false);

  const togglePause = async (): Promise<void> => {
    const next = !paused;
    try {
      await apiSend('/api/logs/pause', 'POST', { paused: next });
      setPaused(next);
      toast.success(next ? '已暂停采集日志' : '继续采集日志');
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`操作失败：${msg}`);
    }
  };

  const clear = async (): Promise<void> => {
    try {
      await apiSend('/api/logs/clear', 'POST');
      await mutate();
      toast.success('已清空');
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`清空失败：${msg}`);
    }
  };

  const entries = data?.entries ?? [];
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">协议日志</h1>
        <p className="text-sm text-muted-foreground">
          展示最近 500 条 SDK 收发字节（仅 Mock 模式被捕获；真实串口暂未拦截）。
        </p>
      </div>
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle className="text-base">最近 {entries.length} 条</CardTitle>
            <CardDescription>
              每条包含方向、cmdType、字节长度、hex 与解码摘要。
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => void togglePause()}>
              {paused ? <Play className="mr-2 h-4 w-4" /> : <Pause className="mr-2 h-4 w-4" />}
              {paused ? '继续' : '暂停'}
            </Button>
            <Button variant="outline" size="sm" onClick={() => void clear()}>
              <Eraser className="mr-2 h-4 w-4" /> 清空
            </Button>
          </div>
        </CardHeader>
        <CardContent className="overflow-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-28">时间</TableHead>
                <TableHead className="w-16">方向</TableHead>
                <TableHead className="w-20">cmd</TableHead>
                <TableHead className="w-16">长度</TableHead>
                <TableHead>摘要</TableHead>
                <TableHead>Hex</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                    暂无日志。先在仪表盘触发一次采集试试。
                  </TableCell>
                </TableRow>
              ) : (
                [...entries].reverse().map((entry) => <LogRow key={entry.id} entry={entry} />)
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function LogRow({ entry }: { entry: LogEntry }): React.ReactElement {
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{timestamp(entry.ts)}</TableCell>
      <TableCell>
        <Badge variant={entry.direction === 'tx' ? 'default' : 'secondary'} className="font-mono text-[10px]">
          {entry.direction === 'tx' ? '→ TX' : '← RX'}
        </Badge>
      </TableCell>
      <TableCell className="font-mono text-xs">
        {entry.cmdType !== null ? `0x${entry.cmdType.toString(16).padStart(2, '0').toUpperCase()}` : '—'}
      </TableCell>
      <TableCell className="font-mono text-xs">{entry.byteLength}</TableCell>
      <TableCell className="text-xs">{entry.summary}</TableCell>
      <TableCell>
        <code className="block max-w-md break-all font-mono text-[10px] text-muted-foreground">
          {entry.hex.length > 96 ? `${entry.hex.slice(0, 96)}…` : entry.hex}
        </code>
      </TableCell>
    </TableRow>
  );
}
