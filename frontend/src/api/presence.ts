import { API_BASE } from './client';

/** Input since the previous beacon, counted by lib/presence.ts (backend audience/bots.ClientSignals):
 *  how much and how machine-like, never what was typed or where. */
export interface Signals {
  /** Mouse moves, and those that jumped more than 300 px at once. */
  mv: number;
  jmp: number;
  /** Mouse presses, and those with (almost) no move before them away from the last press. */
  ck: number;
  ckb: number;
  /** Presses (mouse or touch) at the exact centre of a button, link or field. */
  cc: number;
  tp: number;
  /** Key presses (no auto-repeat), and those less than 12 ms after the one before. */
  ky: number;
  kf: number;
  /** Text typed into a field with no key press (desktop). */
  fill: number;
  wh: number;
  /** The page went to the background. */
  hid: number;
  /** Pointer presses made by a script (not trusted). */
  syn: number;
}

/** What the browser says about itself (backend audience/bots.ClientEnv). */
export interface BrowserEnv {
  /** WebGL on a GPU, in software (headless and cloud browsers) or none. */
  gl?: 'hw' | 'soft' | 'none';
  /** userAgentData.platform or navigator.platform. */
  plat?: string;
  /** navigator.plugins / navigator.languages: how many. */
  pl?: number;
  ln?: number;
  /** window.chrome exists. */
  chr?: boolean;
  /** The window reports no outer size. */
  ow?: boolean;
  /** userAgentData names a headless brand. */
  hl?: boolean;
}

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
  signals?: Partial<Signals>;
  /** Once per page load. */
  env?: BrowserEnv;
}

/** A beacon, so leaving the page does not cancel it; plain text, so no CORS preflight. */
export const sendPresence = (beacon: PresenceBeacon) => {
  const url = `${API_BASE}/presence`;
  const body = JSON.stringify(beacon);
  if (!navigator.sendBeacon?.(url, new Blob([body], { type: 'text/plain' }))) {
    void fetch(url, { method: 'POST', body, headers: { 'Content-Type': 'text/plain' }, keepalive: true, credentials: 'same-origin' }).catch(() => undefined);
  }
};
