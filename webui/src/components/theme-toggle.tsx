'use client';

import { Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useSyncExternalStore } from 'react';

import { Button } from '@/components/ui/button';

const subscribe = (): (() => void) => () => {};
const getSnapshot = (): boolean => true;
const getServerSnapshot = (): boolean => false;

function useHasMounted(): boolean {
  // useSyncExternalStore returns the SSR snapshot during SSR (false), and the
  // client snapshot after hydration (true), without triggering the
  // set-state-in-effect lint rule.
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export function ThemeToggle(): React.ReactElement {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useHasMounted();
  if (!mounted) {
    return (
      <Button variant="ghost" size="icon" aria-label="切换主题" disabled>
        <Sun className="h-4 w-4" />
      </Button>
    );
  }
  const isDark = resolvedTheme === 'dark';
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="切换主题"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
