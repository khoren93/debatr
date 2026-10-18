/** Helpers of the admin console pages (a .ts file for react-refresh). */

/**
 * Where to go after signing in: a console page or sqladmin (`/api/admin/db/`, a full page
 * load), never another origin or path.
 */
export const safeAdminNext = (raw: string | null): string => {
  if (!raw) return '/admin';
  let value: string;
  try {
    value = decodeURIComponent(raw);
  } catch {
    return '/admin';
  }
  if (value.startsWith('//') || value.startsWith('/\\')) return '/admin';
  if (value === '/admin/login' || value.startsWith('/admin/login?')) return '/admin';
  if (value === '/admin' || value.startsWith('/admin/') || value.startsWith('/api/admin/db/')) return value;
  return '/admin';
};

/** "Chrome on macOS" from a user-agent string (good enough to tell sessions apart). */
export const describeAgent = (ua: string): string => {
  const browser =
    (/Edg\//.test(ua) && 'Edge') ||
    (/OPR\//.test(ua) && 'Opera') ||
    (/Firefox\//.test(ua) && 'Firefox') ||
    (/Chrome\//.test(ua) && 'Chrome') ||
    (/Safari\//.test(ua) && 'Safari') ||
    'Browser';
  const os =
    (/iPhone|iPad/.test(ua) && 'iOS') ||
    (/Android/.test(ua) && 'Android') ||
    (/Mac OS X/.test(ua) && 'macOS') ||
    (/Windows/.test(ua) && 'Windows') ||
    (/Linux/.test(ua) && 'Linux') ||
    '';
  return os ? `${browser} on ${os}` : browser;
};

export const formatTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

/** Money of the console: "$12.34", "$0.0064" for fractions of a cent, "$1.2K" from a thousand. */
export const formatUsd = (value: number): string => {
  const abs = Math.abs(value);
  const sign = value < 0 ? '−' : '';
  if (abs === 0) return '$0';
  if (abs < 0.01) return `${sign}$${abs.toFixed(4)}`;
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(abs >= 10_000 ? 0 : 1)}K`;
  return `${sign}$${abs.toFixed(2)}`;
};

/** Axis ticks for money: "$0", "$0.002", "$5". */
export const formatUsdTick = (value: number): string => {
  if (value === 0) return '$0';
  if (value < 0.01) return `$${Number(value.toPrecision(2))}`;
  return formatUsd(value);
};

export const formatPercent = (value: number | null): string =>
  value === null ? '—' : `${(value * 100).toFixed(value > 0 && value < 0.1 ? 1 : 0)}%`;

export const formatSeconds = (ms: number | null): string =>
  ms === null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
