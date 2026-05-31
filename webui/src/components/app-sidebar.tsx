'use client';

import {
  Activity,
  Aperture,
  ChartLine,
  DatabaseZap,
  FileTerminal,
  Settings,
  TrendingUp,
  Wand2,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar';

const ITEMS: ReadonlyArray<{
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  group: string;
}> = [
  { href: '/acquisition', label: '多模态采集', icon: DatabaseZap, group: '采集' },
  { href: '/stream', label: 'H1 实时流', icon: ChartLine, group: '采集' },
  { href: '/debug', label: '本机仪表盘', icon: Activity, group: '本机 H1 调试' },
  { href: '/capture', label: '本机单帧采集', icon: Aperture, group: '本机 H1 调试' },
  { href: '/settings', label: '本机设备设置', icon: Settings, group: '本机 H1 调试' },
  { href: '/curve', label: '本机效率曲线', icon: TrendingUp, group: '本机 H1 调试' },
  { href: '/logs', label: '协议日志', icon: FileTerminal, group: '观察' },
];

export function AppSidebar(): React.ReactElement {
  const pathname = usePathname();
  const groups = Array.from(new Set(ITEMS.map((i) => i.group)));
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1.5">
          <Wand2 className="h-5 w-5 text-primary" />
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold">Spectrum 采集台</span>
            <span className="text-xs text-muted-foreground">树莓派硬件采集</span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        {groups.map((group) => (
          <SidebarGroup key={group}>
            <SidebarGroupLabel>{group}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {ITEMS.filter((i) => i.group === group).map((item) => {
                  const isActive =
                    item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
                  const Icon = item.icon;
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton
                        isActive={isActive}
                        tooltip={item.label}
                        render={
                          <Link href={item.href}>
                            <Icon className="h-4 w-4" />
                            <span>{item.label}</span>
                          </Link>
                        }
                      />
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <p className="px-2 py-1 text-[10px] text-muted-foreground">@h1/sdk · Next.js 16</p>
      </SidebarFooter>
    </Sidebar>
  );
}
