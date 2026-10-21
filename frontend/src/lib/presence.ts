import { isLandingPage } from '../api/debates';
import { sendPresence, type PresenceEvent } from '../api/presence';

/**
 * The presence beacon (backend services/audience; the admin console's Audience page): pages
 * shown, the time each stays in front of the visitor and the actions that matter.
 *
 * A visitor id lives in localStorage for good; a visit (shared by the tabs) ends after
 * VISIT_IDLE_MS without activity, or when the visitor arrives again from another site. A page
 * left open past that starts a new visit when the visitor comes back to it ("resumed": no landing
 * of its own). Time counts while the page is visible and the visitor did something in the last
 * IDLE_MS (a debate's video runs for minutes without a click) and always goes to the visit the
 * page was shown in. Events are batched and sent with `navigator.sendBeacon`, at once when the
 * page is hidden or left. Browser only: nothing is sent on the server, by a browser driven by
 * automation, or while the admin console's `analytics_enabled` lever is off.
 */

/** Actions the site reports; the backend keeps only these (audience/collect.ACTIONS). */
export type PresenceAction =
  | 'signup'
  | 'login'
  | 'logout'
  | 'video_play'
  | 'video_progress'
  | 'like'
  | 'vote'
  | 'share'
  | 'copy_link'
  | 'copy_embed'
  | 'remix'
  | 'verdict_reveal'
  | 'export_mp4'
  | 'download_mp3'
  | 'wizard_step'
  | 'topic_pick'
  | 'topic_ideas'
  | 'debate_start'
  | 'draft_save'
  | 'checkout'
  | 'topup'
  | 'cli_login'
  | 'token_create'
  | 'gallery_filter';

type Props = Record<string, string | number | boolean | null>;

const VISITOR_KEY = 'debatr.visitor';
const VISIT_KEY = 'debatr.visit';
export const VISIT_IDLE_MS = 30 * 60_000;
export const IDLE_MS = 15 * 60_000;
const PING_MS = 60_000;
const FLUSH_DELAY_MS = 1500;
const MAX_QUEUE = 40;
const MAX_TIME_MS = 30 * 60_000;

interface Visit {
  id: string;
  at: number;
}

interface Page {
  id: string;
  path: string;
  visit: string;
  shownAt: number;
  /** Start of the time not reported yet; null while the page is hidden. */
  since: number | null;
}

let enabled = true;
let started = false;
let documentPages = 0;
let page: Page | null = null;
let lastInput = 0;
let queue: PresenceEvent[] = [];
let queueVisit: { id: string; resumed: boolean } | null = null;
let flushTimer: ReturnType<typeof setTimeout> | null = null;
const memory: { visitor: string | null; visit: Visit | null } = { visitor: null, visit: null };

const active = () => enabled && typeof window !== 'undefined' && !navigator.webdriver;
const visible = () => document.visibilityState === 'visible';

const read = (key: string): string | null => {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
};

const write = (key: string, value: string) => {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private mode or blocked storage: the ids live as long as this page.
  }
};

const newId = (): string => {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hex = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

const visitorId = (): string => {
  const stored = read(VISITOR_KEY);
  if (stored) return stored;
  memory.visitor ??= newId();
  write(VISITOR_KEY, memory.visitor);
  return memory.visitor;
};

const storedVisit = (): Visit | null => {
  try {
    const raw = read(VISIT_KEY);
    if (raw) return JSON.parse(raw) as Visit;
  } catch {
    // An unreadable entry counts as none.
  }
  return memory.visit;
};

const saveVisit = (visit: Visit) => {
  memory.visit = visit;
  write(VISIT_KEY, JSON.stringify(visit));
};

/** Whether a visit last active at `last` is over at `now`. */
export const visitExpired = (last: number, now: number) => now - last > VISIT_IDLE_MS;

/** Time of a shown page not reported yet: visible, and up to IDLE_MS after the last input. */
export const engagedSince = (since: number | null, now: number, lastInputAt: number) => (since === null ? 0 : Math.max(0, Math.min(now, lastInputAt + IDLE_MS) - since));

const flush = () => {
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = null;
  if (queue.length && queueVisit && active()) {
    sendPresence({
      visitor: visitorId(),
      visit: queueVisit.id,
      events: queue,
      screen: window.screen ? `${window.screen.width}x${window.screen.height}` : undefined,
      lang: navigator.language?.slice(0, 16),
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone?.slice(0, 48),
      touch: navigator.maxTouchPoints > 1,
      resumed: queueVisit.resumed || undefined,
    });
    queueVisit = { id: queueVisit.id, resumed: false };
  }
  queue = [];
};

const enqueue = (visit: string, event: PresenceEvent, resumed = false) => {
  if (queueVisit && queueVisit.id !== visit) flush();
  if (!queueVisit || queueVisit.id !== visit) queueVisit = { id: visit, resumed };
  queue.push(event);
  if (queue.length >= MAX_QUEUE) flush();
  else flushTimer ??= setTimeout(flush, FLUSH_DELAY_MS);
};

/** Report the shown page's time (to the visit it was shown in) and keep that visit going. */
const collect = (now: number) => {
  if (!page || page.since === null) return;
  const ms = Math.round(engagedSince(page.since, now, lastInput));
  page.since = visible() ? now : null;
  if (ms < 500) return;
  enqueue(page.visit, { type: 'time', id: page.id, path: page.path, ms: Math.min(ms, MAX_TIME_MS) });
  const current = storedVisit();
  if (current?.id === page.visit && !visitExpired(current.at, now)) saveVisit({ id: page.visit, at: now });
};

/** The shown page in the visit going on now: its own, or (it is over, or another tab began
 *  one) the shown page opens the new one. */
const followVisit = (now: number) => {
  if (!page) return;
  const current = storedVisit();
  if (current && !visitExpired(current.at, now)) {
    saveVisit({ id: current.id, at: now });
    if (current.id === page.visit) return;
  }
  const resumed = !current || visitExpired(current.at, now);
  const id = resumed ? newId() : (current?.id ?? newId());
  saveVisit({ id, at: now });
  page = { ...page, id: newId(), visit: id, shownAt: now, since: visible() ? now : null };
  enqueue(id, { type: 'page', id: page.id, path: page.path }, resumed);
};

const onInput = () => {
  const now = Date.now();
  const away = now - lastInput;
  if (away > PING_MS) {
    // Back after a pause: the time before it stops at the idle limit.
    collect(now);
    if (page && visible()) page.since = now;
    followVisit(now);
  }
  lastInput = now;
};

const start = () => {
  if (started) return;
  started = true;
  lastInput = Date.now();
  let throttled = 0;
  const input = () => {
    const now = Date.now();
    if (now - throttled < 1000) return;
    throttled = now;
    onInput();
  };
  for (const name of ['pointerdown', 'keydown', 'scroll', 'touchstart', 'mousemove'] as const) window.addEventListener(name, input, { passive: true, capture: true });
  document.addEventListener('visibilitychange', () => {
    const now = Date.now();
    if (!visible()) {
      collect(now);
      flush();
    } else if (page) {
      page.since = now;
      lastInput = now;
      followVisit(now);
    }
  });
  window.addEventListener('pagehide', () => {
    collect(Date.now());
    flush();
  });
  setInterval(() => {
    if (visible()) collect(Date.now());
  }, PING_MS);
};

/** The admin console's lever (`GET /api/status`): off sends nothing. */
export const setPresenceEnabled = (on: boolean) => {
  enabled = on;
  if (!on) queue = [];
};

const externalReferrer = (): string | undefined => {
  try {
    const referrer = document.referrer;
    return referrer && new URL(referrer).host !== window.location.host ? referrer : undefined;
  } catch {
    return undefined;
  }
};

/** A page was shown (the router's location changed). */
export const pageShown = (path: string, search: string) => {
  if (!active()) return;
  start();
  const now = Date.now();
  // The same page again at once (React's development double effects, a replaced URL).
  if (page && page.path === path && now - page.shownAt < 1000) return;
  collect(now);
  const landing = documentPages === 0 && isLandingPage();
  documentPages += 1;
  const referrer = landing ? externalReferrer() : undefined;
  const current = storedVisit();
  // Arriving again from another site starts a new visit, credited to that site.
  const fresh = referrer !== undefined || !current || visitExpired(current.at, now);
  const visit = fresh ? newId() : (current?.id ?? newId());
  saveVisit({ id: visit, at: now });
  page = { id: newId(), path, visit, shownAt: now, since: visible() ? now : null };
  lastInput = now;
  const event: PresenceEvent = { type: 'page', id: page.id, path };
  if (fresh && landing) Object.assign(event, { query: search || undefined, referrer });
  enqueue(visit, event, fresh && !landing);
};

/** Something the visitor did (`debate`: the debate it concerns). */
export const track = (name: PresenceAction, props: Props = {}, debate?: string) => {
  if (!active() || !page) return;
  const now = Date.now();
  lastInput = now;
  followVisit(now);
  enqueue(page.visit, { type: 'action', name, path: window.location.pathname, debate, props });
};

