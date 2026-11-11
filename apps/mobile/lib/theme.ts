import { useColorScheme } from '@/components/useColorScheme';

const light = {
  bg: '#f6f7fb',
  surface: '#ffffff',
  text: '#14213d',
  muted: '#5c677d',
  border: '#e3e6ee',
  brand: '#14213d',
  onBrand: '#ffffff',
  accent: '#fca311',
  tint: '#2563eb',
  ok: '#1f8a4c',
  info: '#2563eb',
  warn: '#b45309',
  bad: '#c0392b',
};

const dark: typeof light = {
  bg: '#0e1424',
  surface: '#161e33',
  text: '#e8ecf5',
  muted: '#9aa6bf',
  border: '#273352',
  brand: '#fca311',
  onBrand: '#14213d',
  accent: '#fca311',
  tint: '#fca311',
  ok: '#4ade80',
  info: '#60a5fa',
  warn: '#fbbf24',
  bad: '#f87171',
};

export type Palette = typeof light;

export function useTheme(): Palette {
  return useColorScheme() === 'dark' ? dark : light;
}

export const STATUS_TONE: Record<string, keyof Palette> = {
  completed: 'ok',
  succeeded: 'ok',
  active: 'ok',
  running: 'info',
  verifying: 'info',
  planned: 'info',
  queued: 'info',
  waiting_for_tool: 'warn',
  waiting_for_approval: 'warn',
  sandbox: 'warn',
  blocked: 'warn',
  suspended: 'warn',
  failed: 'bad',
  expired: 'bad',
  retired: 'muted',
  cancelled: 'muted',
  draft: 'muted',
  pending: 'muted',
};

export function statusLabel(status: string): string {
  const text = status.replaceAll('_', ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}
