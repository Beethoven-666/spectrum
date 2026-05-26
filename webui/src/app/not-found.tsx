import Link from 'next/link';

import { Button } from '@/components/ui/button';

export default function NotFound(): React.ReactElement {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-24 text-center">
      <h1 className="text-3xl font-semibold">404</h1>
      <p className="text-sm text-muted-foreground">没有这个页面。回到仪表盘看看？</p>
      <Button render={<Link href="/" />}>返回仪表盘</Button>
    </div>
  );
}
