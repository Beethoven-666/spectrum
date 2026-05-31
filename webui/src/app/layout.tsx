import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

import { Toaster } from '@/components/ui/sonner';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { TooltipProvider } from '@/components/ui/tooltip';

import { AppSidebar } from '@/components/app-sidebar';
import { ConnectionBar } from '@/components/connection-bar';
import { ThemeProvider } from '@/components/theme-provider';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'Spectrum 采集台 · 树莓派硬件采集',
  description: '树莓派 H1 光谱仪与 D455 多模态采集界面',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>): React.ReactElement {
  return (
    <html
      lang="zh-CN"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <ThemeProvider>
          <TooltipProvider delay={250}>
            <SidebarProvider>
              <AppSidebar />
              <SidebarInset className="flex min-h-screen flex-col">
                <ConnectionBar />
                <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
              </SidebarInset>
            </SidebarProvider>
            <Toaster richColors closeButton position="top-right" />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
