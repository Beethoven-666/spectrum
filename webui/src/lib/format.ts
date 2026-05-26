/**
 * Shared number/time formatters using Intl.
 */

const numberFmts = new Map<string, Intl.NumberFormat>();

export function num(value: number, opts?: Intl.NumberFormatOptions): string {
  if (!Number.isFinite(value)) return '—';
  const key = JSON.stringify(opts ?? {});
  let fmt = numberFmts.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat('zh-CN', opts);
    numberFmts.set(key, fmt);
  }
  return fmt.format(value);
}

export const numFixed = (v: number, digits: number): string =>
  num(v, { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const numInt = (v: number): string => num(v, { maximumFractionDigits: 0 });

const tsFmt = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  fractionalSecondDigits: 3,
  hour12: false,
});

export const timestamp = (ms: number): string => tsFmt.format(new Date(ms));
