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
