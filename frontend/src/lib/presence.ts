import { isLandingPage } from '../api/debates';
import { sendPresence, type BrowserEnv, type PresenceEvent, type Signals } from '../api/presence';

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
 *
 * Each beacon also carries counts of the input since the previous one (mouse moves, presses,
 * touches, keys, wheel scrolls) and how machine-like it was (presses with no mouse path towards
 * them or at the exact centre of a button, keys faster than fingers, text with no keys), and once
 * per page load what the browser says about itself (graphics on a GPU or in software, platform,
 * a headless brand…): the console tells people from bots and AI agents with them (backend
 * audience/bots.py). Never what was typed, nor where the pointer went.
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

type UAData = { platform?: string; brands?: { brand: string }[] };

const VISITOR_KEY = 'debatr.visitor';
const VISIT_KEY = 'debatr.visit';
export const VISIT_IDLE_MS = 30 * 60_000;
export const IDLE_MS = 15 * 60_000;
const PING_MS = 60_000;
const FLUSH_DELAY_MS = 1500;
const MAX_QUEUE = 40;
const MAX_TIME_MS = 30 * 60_000;
const JUMP_PX = 300;
const FAST_KEY_MS = 12;
const CENTRE_PX = 0.5;
const PRESSABLE = 'a,button,input,select,textarea,label,summary,[role="button"],[role="link"],[role="tab"],[role="option"],[role="menuitem"],[tabindex]';
const SOFTWARE_GL = /swiftshader|llvmpipe|softpipe|software|basic render|mesa offscreen/i;

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

const noSignals = (): Signals => ({ mv: 0, jmp: 0, ck: 0, ckb: 0, cc: 0, tp: 0, ky: 0, kf: 0, fill: 0, wh: 0, hid: 0, syn: 0 });
let signals = noSignals();
// The browser's facts: worked out in idle time, sent with the next beacon, once per page load.
let env: BrowserEnv | null = null;
let envSent = false;

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

/** The counts since the previous beacon (only those above zero; an empty object still says the
 *  page counts: no input at all is a signal too), starting the next ones at zero. */
const takeSignals = (): Partial<Signals> => {
  const counted = Object.fromEntries(Object.entries(signals).filter(([, n]) => n > 0));
  signals = noSignals();
  return counted;
};

const takeEnv = (): BrowserEnv | undefined => {
  if (!env || envSent) return undefined;
  envSent = true;
  return env;
};

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
      signals: takeSignals(),
      env: takeEnv(),
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

/** WebGL's renderer, as a class only: a GPU, software rendering or none. */
const graphics = (): BrowserEnv['gl'] => {
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    if (!gl) return 'none';
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER) ?? '');
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return SOFTWARE_GL.test(renderer) ? 'soft' : 'hw';
  } catch {
    return undefined;
  }
};

const browserEnv = (): BrowserEnv => {
  const ua = (navigator as Navigator & { userAgentData?: UAData }).userAgentData;
  return {
    gl: graphics(),
    plat: (ua?.platform || navigator.platform || '').slice(0, 32) || undefined,
    pl: navigator.plugins?.length,
    ln: navigator.languages?.length,
    chr: 'chrome' in window,
    ow: window.outerWidth === 0 && window.outerHeight === 0,
    hl: ua?.brands?.some((b) => /headless/i.test(b.brand)) || undefined,
  };
};

/** A press at the exact centre of what it pressed (where software clicks; a hand almost never). */
const centred = (e: PointerEvent): boolean => {
  const target = e.target instanceof Element ? e.target.closest(PRESSABLE) : null;
  if (!target) return false;
  const box = target.getBoundingClientRect();
  if (box.width < 8 || box.height < 8) return false;
  return Math.abs(e.clientX - (box.left + box.width / 2)) <= CENTRE_PX && Math.abs(e.clientY - (box.top + box.height / 2)) <= CENTRE_PX;
};

/** Counts the input (Signals): how much of it, and how machine-like. */
const watchInput = () => {
  const options = { passive: true, capture: true } as const;
  const desktop = navigator.maxTouchPoints === 0;
  let pointer: { x: number; y: number } | null = null;
  let lastPress: { x: number; y: number } | null = null;
  let movesSincePress = 0;
  let lastKeyAt = -Infinity;
  window.addEventListener(
    'pointermove',
    (e) => {
      if (e.pointerType !== 'mouse' || !e.isTrusted) return;
      signals.mv += 1;
      movesSincePress += 1;
      if (pointer && Math.hypot(e.clientX - pointer.x, e.clientY - pointer.y) > JUMP_PX) signals.jmp += 1;
      pointer = { x: e.clientX, y: e.clientY };
    },
    options,
  );
  // The pointer may come back anywhere.
  const lose = () => {
    pointer = null;
  };
  document.documentElement.addEventListener('pointerleave', lose, options);
  window.addEventListener('blur', lose, options);
  window.addEventListener(
    'pointerdown',
    (e) => {
      if (!e.isTrusted) {
        signals.syn += 1;
        return;
      }
      if (e.pointerType === 'mouse') {
        signals.ck += 1;
        const again = lastPress && Math.hypot(e.clientX - lastPress.x, e.clientY - lastPress.y) < 12;
        if (movesSincePress <= 1 && !again) signals.ckb += 1;
        movesSincePress = 0;
        lastPress = { x: e.clientX, y: e.clientY };
      } else {
        signals.tp += 1;
      }
      if (centred(e)) signals.cc += 1;
    },
    options,
  );
  window.addEventListener(
    'keydown',
    (e) => {
      if (!e.isTrusted || e.repeat) return;
      const now = performance.now();
      signals.ky += 1;
      if (now - lastKeyAt < FAST_KEY_MS) signals.kf += 1;
      lastKeyAt = now;
    },
    options,
  );
  window.addEventListener(
    'input',
    (e) => {
      // Phones type through their keyboards, dictation and suggestions without key presses.
      if (!desktop || !e.isTrusted || (e as InputEvent).inputType !== 'insertText') return;
      if (performance.now() - lastKeyAt > 100) signals.fill += 1;
    },
    options,
  );
  window.addEventListener(
    'wheel',
    (e) => {
      if (e.isTrusted) signals.wh += 1;
    },
    options,
  );
};

const start = () => {
  if (started) return;
  started = true;
  lastInput = Date.now();
  watchInput();
  const describe = () => {
    env = browserEnv();
  };
  if (typeof window.requestIdleCallback === 'function') window.requestIdleCallback(describe, { timeout: 3000 });
  else setTimeout(describe, 1000);
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
      signals.hid += 1;
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
  if (!on) {
    queue = [];
    signals = noSignals();
  }
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

