import { API_BASE } from './client';

/** One presence beacon (backend services/audience/collect.py). */
export interface PresenceEvent {
  type: 'page' | 'time' | 'action';
  id?: string;
  path: string;
  query?: string;
  referrer?: string;
  ms?: number;
  name?: string;
  debate?: string;
  props?: Record<string, string | number | boolean | null>;
}

export interface PresenceBeacon {
  visitor: string;
  visit: string;
  events: PresenceEvent[];
  screen?: string;
  lang?: string;
  tz?: string;
  touch?: boolean;
  resumed?: boolean;
}

/** A beacon, so leaving the page does not cancel it; plain text, so no CORS preflight. */
export const sendPresence = (beacon: PresenceBeacon) => {
  const url = `${API_BASE}/presence`;
  const body = JSON.stringify(beacon);
  if (!navigator.sendBeacon?.(url, new Blob([body], { type: 'text/plain' }))) {
    void fetch(url, { method: 'POST', body, headers: { 'Content-Type': 'text/plain' }, keepalive: true, credentials: 'same-origin' }).catch(() => undefined);
  }
};
