import { Badge } from '@/components/ui/badge';

/** Map ExposureStatus enum byte → label + variant. */
export function ExposureStatusBadge({ status }: { status: number }): React.ReactElement {
  switch (status) {
    case 0x01:
      return <Badge variant="destructive">过曝</Badge>;
    case 0x02:
      return (
        <Badge className="bg-amber-500 text-white hover:bg-amber-500/90 dark:bg-amber-400 dark:text-amber-950">
          欠曝
        </Badge>
      );
    case 0x00:
    default:
      return (
        <Badge className="bg-emerald-500 text-white hover:bg-emerald-500/90 dark:bg-emerald-400 dark:text-emerald-950">
          正常
        </Badge>
      );
  }
}
