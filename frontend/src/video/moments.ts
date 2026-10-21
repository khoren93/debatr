import type { Timeline, TimelineMoment } from '../api/timeline';

/**
 * How the video hits a line that lands (`Timeline.moments`), free of Remotion (unit-tested): the
 * camera pushes in while it is said and lets go after it; as its last word lands a battle's
 * punchline flashes, shakes the frame and makes the other rapper flinch, a debate's zinger only
 * flashes softly. Deterministic: the same frame always looks the same.
 */

/** The push starts building this long before the line's first word. */
const LEAD_MS = 150;
/** After the last word: the push holds, then lets go. */
const HOLD_MS = 250;
const RELEASE_MS = 500;
const FLASH_MS = 260;
const SHAKE_MS = 380;
const FLINCH_MS = 650;
const LAND_MS = 300;

export interface Hit {
  moment: TimelineMoment;
  /** Extra camera scale (0 when nothing is building up). */
  push: number;
  flash: number;
  shake: { x: number; y: number };
  /** 1 as the line lands, fading: the other rapper's card shakes and reddens. */
  flinch: number;
  /** 0 → 1 over the first moments after the last word: the line's slam. */
  landed: number;
}

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const smooth = (x: number) => x * x * (3 - 2 * x);

/** The moment whose window holds `ms` (a later one wins an overlap). */
export const momentAt = (timeline: Pick<Timeline, 'moments'>, ms: number): TimelineMoment | null => {
  let found: TimelineMoment | null = null;
  for (const m of timeline.moments ?? []) {
    if (ms >= m.start_ms - LEAD_MS && ms < m.end_ms + HOLD_MS + RELEASE_MS) found = m;
  }
  return found;
};

export const hitAt = (timeline: Pick<Timeline, 'moments'>, ms: number): Hit | null => {
  const moment = momentAt(timeline, ms);
  if (!moment) return null;
  const punch = moment.kind === 'punchline';
  const strength = moment.big ? 1.5 : 1;
  const build = smooth(clamp01((ms - moment.start_ms + LEAD_MS) / Math.max(1, moment.end_ms - moment.start_ms + LEAD_MS)));
  const release = 1 - smooth(clamp01((ms - moment.end_ms - HOLD_MS) / RELEASE_MS));
  const since = ms - moment.end_ms;
  const after = since >= 0;
  const fade = (span: number) => (after ? clamp01(1 - since / span) : 0);
  const amp = punch ? 9 * strength * fade(SHAKE_MS) ** 2 : 0;
  return {
    moment,
    push: (punch ? 0.03 : 0.015) * strength * Math.min(build, release),
    flash: (punch ? 0.1 : 0.04) * strength * fade(FLASH_MS),
    shake: amp > 0 ? { x: amp * Math.sin(since / 10), y: amp * 0.6 * Math.cos(since / 12) } : { x: 0, y: 0 },
    flinch: punch ? fade(FLINCH_MS) : 0,
    landed: after ? clamp01(since / LAND_MS) : 0,
  };
};

/** The words of a turn that are this moment's line (by time, with a little slack). */
export const inMoment = (moment: TimelineMoment | null | undefined, fromMs: number, toMs: number): boolean =>
  Boolean(moment && fromMs >= moment.start_ms - 30 && toMs <= moment.end_ms + 30);
