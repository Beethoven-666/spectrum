'use client';

import { Loader2, RotateCcw, Upload } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { ApiCallError, apiSend } from '@/lib/api-client';
import { numInt } from '@/lib/format';
import { useConnectionStore } from '@/store/connection';

export default function CurvePage(): React.ReactElement {
  const connected = useConnectionStore((s) => s.status.connected);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<'upload' | 'reset' | null>(null);

  const parse = (): number[] | null => {
    const values: number[] = [];
    const lines = text.split(/[\s,;\r\n]+/);
    for (const t of lines) {
      if (!t) continue;
      const v = Number(t);
      if (!Number.isFinite(v)) {
        toast.error(`无法解析为浮点数：${t}`);
        return null;
      }
      values.push(v);
    }
    if (values.length === 0) {
      toast.error('请输入至少一个数值');
      return null;
    }
    return values;
  };

  const upload = async (): Promise<void> => {
    const ratios = parse();
    if (!ratios) return;
    setBusy('upload');
    try {
      await apiSend('/api/device/efficiency-curve', 'POST', { ratios });
      toast.success(`已发送 ${numInt(ratios.length)} 个 ratio 并触发校验`);
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`上传失败：${msg}`);
    } finally {
      setBusy(null);
    }
  };

  const reset = async (): Promise<void> => {
    setBusy('reset');
    try {
      await apiSend('/api/device/efficiency-curve/reset', 'POST');
      toast.success('已恢复出厂效率曲线');
    } catch (err) {
      const msg = err instanceof ApiCallError ? err.message : String(err);
      toast.error(`重置失败：${msg}`);
    } finally {
      setBusy(null);
    }
  };

  const handleFile = async (file: File): Promise<void> => {
    const t = await file.text();
    setText(t);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">效率曲线</h1>
        <p className="text-sm text-muted-foreground">
          上传 ratio 浮点数组（每行一个或逗号分隔），分包发送后触发 0x27 校验并写入 flash。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">上传效率曲线</CardTitle>
          <CardDescription>
            SDK 会自动按 ≤247 个 float / 包分包；发送完成后会调用 0x27。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            rows={12}
            placeholder="例如：&#10;1.0&#10;1.05&#10;1.1&#10;…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={busy !== null || !connected}
            className="font-mono text-xs"
          />
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="file"
              accept=".csv,.txt"
              id="curve-file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleFile(f);
              }}
              className="hidden"
            />
            <Button
              variant="outline"
              onClick={() => document.getElementById('curve-file')?.click()}
              disabled={busy !== null}
            >
              选择 .csv 或 .txt
            </Button>
            <Button onClick={() => void upload()} disabled={busy !== null || !connected}>
              {busy === 'upload' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
              上传并校验
            </Button>
            <Button variant="outline" onClick={() => void reset()} disabled={busy !== null || !connected}>
              {busy === 'reset' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RotateCcw className="mr-2 h-4 w-4" />}
              恢复出厂
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
