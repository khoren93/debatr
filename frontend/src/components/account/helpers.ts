/** Helpers shared by the account and auth pages (kept in a .ts file for react-refresh). */

/** "$4.67" / "−$0.50" — always two decimals, real minus sign. */
export const money = (n: number) => `${n < 0 ? '−' : ''}$${Math.abs(n).toFixed(2)}`;

/** "$10" for whole amounts, "$2.50" otherwise (top-up chips and buttons). */
export const moneyShort = (n: number) => (Number.isInteger(n) ? `$${n}` : money(n));

/** "debate_charge" -> "Debate charge". */
export const humanizeKind = (kind: string) => {
  const text = kind.replace(/[_-]+/g, ' ').trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Transaction';
};

const AUTH_PATHS = ['/login', '/register'];

/** Sanitized `?next=` redirect target: only same-origin paths are allowed (never `//host` or the auth pages). */
export const safeNext = (raw: string | null): string | null => {
  if (!raw) return null;
  let value = raw;
  if (!value.startsWith('/')) {
    try {
      value = decodeURIComponent(value);
    } catch {
      return null;
    }
  }
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return null;
  if (AUTH_PATHS.some((p) => value === p || value.startsWith(`${p}?`))) return null;
  return value;
};

/** Append the preserved `next` target to an auth route. */
export const withNext = (path: string, next: string | null) =>
  next ? `${path}?next=${encodeURIComponent(next)}` : path;

const RELATIVE = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
];

/** "2 hours ago" / "in 3 days" / "just now". */
export const timeAgo = (iso: string, now: number = Date.now()) => {
  const seconds = (new Date(iso).getTime() - now) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return RELATIVE.format(Math.round(seconds / size), unit);
  }
  return 'just now';
};

/** "Oct 2026" */
export const monthYear = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });

/** "18:42" in the visitor's time zone. */
export const clockTime = (iso: string) => new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** Local calendar day of a timestamp, for grouping ledger rows ("2026-10-14"). */
export const localDay = (iso: string) => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const BROWSERS: [RegExp, string][] = [
  [/Edg\//, 'Edge'],
  [/OPR\/|Opera/, 'Opera'],
  [/Firefox\/|FxiOS/, 'Firefox'],
  [/Chrome\/|CriOS/, 'Chrome'],
  [/Safari\//, 'Safari'],
];
const SYSTEMS: [RegExp, string][] = [
  [/iPhone|iPad|iPod/, 'iOS'],
  [/Android/, 'Android'],
  [/CrOS/, 'ChromeOS'],
  [/Mac OS X|Macintosh/, 'macOS'],
  [/Windows/, 'Windows'],
  [/Linux/, 'Linux'],
];

/** "Chrome on macOS" from a user agent string (null when nothing is recognised). */
export const describeDevice = (ua: string) => {
  const browser = BROWSERS.find(([re]) => re.test(ua))?.[1];
  const system = SYSTEMS.find(([re]) => re.test(ua))?.[1];
  if (browser && system) return `${browser} on ${system}`;
  return browser ?? system ?? null;
};
