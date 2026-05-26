'use client';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}): React.ReactElement {
  return (
    <html lang="zh-CN">
      <body style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem' }}>
        <h1>致命错误</h1>
        <pre style={{ background: '#fee', padding: '1rem', overflow: 'auto' }}>{error.message}</pre>
        <button onClick={() => reset()}>重试</button>
      </body>
    </html>
  );
}
