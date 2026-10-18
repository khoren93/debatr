import type { AlertEvent, AlertGroup } from '../../api/admin/types';

export const ALERT_GROUPS: { group: AlertGroup; label: string }[] = [
  { group: 'security', label: 'Console security' },
  { group: 'people', label: 'Accounts and money' },
  { group: 'debates', label: 'Debates' },
  { group: 'system', label: 'Providers and server' },
];

/** "New debate, Top-ups muted" or "all on" (the change dialog, the .env line). */
export const mutedSummary = (muted: string[], events: AlertEvent[]): string => {
  if (!muted.length) return 'all on';
  const labels = new Map(events.map((e) => [e.kind, e.label]));
  return `${muted.map((kind) => labels.get(kind) ?? kind).join(', ')} muted`;
};

export const mutesSecurity = (muted: string[], events: AlertEvent[]): boolean =>
  events.some((e) => e.group === 'security' && muted.includes(e.kind));
