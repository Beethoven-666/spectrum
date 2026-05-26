'use client';

import { TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): React.ReactElement {
  return (
    <div className="mx-auto max-w-xl py-16">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TriangleAlert className="h-5 w-5 text-destructive" /> 页面出现错误
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <pre className="overflow-auto rounded bg-muted p-3 font-mono text-xs">
            {error.message}
            {error.digest ? `\ndigest: ${error.digest}` : ''}
          </pre>
          <Button onClick={() => reset()}>重试</Button>
        </CardContent>
      </Card>
    </div>
  );
}
