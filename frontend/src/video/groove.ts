import type { Timeline, TimelineBeat, TimelineSegment } from '../api/timeline';
import { levelAt, roundLabel } from './timing';

/**
 * What makes the frame move with the show, free of Remotion (unit-tested): the beat of a rap
 * battle's track, the glow colour following the speaker, the "ROUND N" cards and the camera.
 */

/** A beat's flash fades with this time constant. */
export const BEAT_DECAY_MS = 160;
/** The tempo battle tracks are made at (backend media/music.BPM), for timelines without a grid. */
export const BATTLE_BPM = 92;
/** The glow takes this long to turn from one speaker's colour to the next one's. */
export const COLOR_MS = 700;

export interface Groove {
  /** 1 on a beat, decaying to 0 before the next one. */
  pulse: number;
  /** The beat carries the kick. */
  strong: boolean;
  /** Beats since the grid's start (fractional): motion that follows the bars. */
  phase: number;
}

export const beatAt = (beat: TimelineBeat, ms: number): Groove => {
  const period = 60_000 / beat.bpm;
  const phase = (ms - beat.offset_ms) / period;
  const k = Math.floor(phase);
  return { pulse: Math.exp(-((phase - k) * period) / BEAT_DECAY_MS), strong: (((k % 2) + 2) % 2) === beat.accent, phase };
};

/** A battle's groove: on the measured beat, else (older timelines) on the track's loudness. */
export const grooveAt = (timeline: Pick<Timeline, 'beat'>, seg: TimelineSegment | null, ms: number): Groove =>
  timeline.beat ? beatAt(timeline.beat, ms) : { pulse: levelAt(seg, ms) ** 3, strong: true, phase: ms / (60_000 / BATTLE_BPM) };

const rgb = (hex: string): [number, number, number] => {
  const m = /^#?([0-9a-f]{6})/i.exec(hex.trim());
  const n = m ? parseInt(m[1], 16) : 0;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

export const mixColor = (a: string, b: string, t: number): string => {
  const x = rgb(a);
  const y = rgb(b);
  const k = Math.max(0, Math.min(1, t));
  return `#${x.map((v, i) => Math.round(v + (y[i] - v) * k).toString(16).padStart(2, '0')).join('')}`;
};

export const withAlpha = (hex: string, alpha: number): string => `rgba(${rgb(hex).join(',')},${Math.max(0, Math.min(1, alpha)).toFixed(3)})`;

const smooth = (x: number) => x * x * (3 - 2 * x);

/** The colour the frame glows in at `ms`: the speaker's, turning from the one before. */
export const glowColorAt = (timeline: Pick<Timeline, 'segments' | 'speakers'>, ms: number, fallback: string): string => {
  const color = (seg: TimelineSegment | undefined) => timeline.speakers.find((s) => s.id === seg?.speaker_id)?.color ?? fallback;
  let i = -1;
  for (let j = 0; j < timeline.segments.length && timeline.segments[j].start_ms <= ms; j++) i = j;
  if (i < 0) return fallback;
  const seg = timeline.segments[i];
  const t = smooth(Math.max(0, Math.min(1, (ms - seg.start_ms) / COLOR_MS)));
  return mixColor(color(timeline.segments[i - 1]), color(seg), t);
};

/** A "ROUND N" card: it slams in at `slamMs` (a beat in a battle) and leaves at `endMs`. */
export interface RoundCard {
  label: string;
  slamMs: number;
  endMs: number;
  /** A battle's card: a flash and a shake; a debate's is quiet. */
  loud: boolean;
}

/** A battle's card needs this much room between the turns. */
const MIN_ROOM_MS = 800;
const DEBATE_CARD_MS = 1500;

const roundNumber = (roundId: string) => Number(/^round_(\d+)$/.exec(roundId)?.[1] ?? 0);

/** The first beat at or after `ms`, a kick beat when one comes before `before`. */
const beatFrom = (beat: TimelineBeat, ms: number, before: number): number => {
  const period = 60_000 / beat.bpm;
  const k = Math.ceil((ms - beat.offset_ms) / period);
  const kick = ((k % 2) + 2) % 2 === beat.accent ? k : k + 1;
  const at = (n: number) => beat.offset_ms + n * period;
  return at(kick) < before ? at(kick) : at(k);
};

const cardsCache = new WeakMap<Timeline, RoundCard[]>();

/** A battle: a card in the beat before the first verse of every round (after the MC, in the
 *  break between rounds). A debate: a quiet one as round 2 and later begin. */
export const roundCards = (timeline: Timeline): RoundCard[] => {
  const cached = cardsCache.get(timeline);
  if (cached) return cached;
  const segs = timeline.segments;
  const cards: RoundCard[] = [];
  const battle = segs.some((s) => s.turn_type === 'verse');
  let lastRound = '';
  segs.forEach((seg, i) => {
    const label = roundLabel(seg.round_id, seg.round_label).toUpperCase();
    if (battle) {
      if (seg.turn_type !== 'verse' || seg.round_id === lastRound) return;
      lastRound = seg.round_id;
      const start = (i > 0 ? segs[i - 1].end_ms : 0) + 150;
      if (seg.start_ms - start < MIN_ROOM_MS) return;
      const slam = timeline.beat ? beatFrom(timeline.beat, start, seg.start_ms - 300) : start;
      cards.push({ label, slamMs: slam, endMs: seg.start_ms + 150, loud: true });
    } else if (i > 0 && seg.round_id !== segs[i - 1].round_id && roundNumber(seg.round_id) >= 2) {
      cards.push({ label, slamMs: seg.start_ms, endMs: seg.start_ms + DEBATE_CARD_MS, loud: false });
    }
  });
  cardsCache.set(timeline, cards);
  return cards;
};

/** The card fades out over this long after its end. */
export const CARD_OUT_MS = 220;

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

/** How much a "ROUND N" card covers the stage at `ms` (fading in as it slams, out after its end). */
export const cardCover = (card: RoundCard | null, ms: number): number =>
  card ? clamp01((ms - card.slamMs) / 80) * (1 - clamp01((ms - card.endMs) / CARD_OUT_MS)) : 0;

/** How much the stage clears for a card: from a beat before it slams in (nothing under the slam)
 *  until it fades out. */
export const stageHush = (card: RoundCard | null, ms: number): number =>
  card ? clamp01((ms - card.slamMs + HUSH_MS) / HUSH_MS) * (1 - clamp01((ms - card.endMs) / CARD_OUT_MS)) : 0;

/** The stage starts clearing this long before a card slams in. */
const HUSH_MS = 160;

export const roundCardAt = (timeline: Timeline, ms: number): RoundCard | null =>
  roundCards(timeline).find((card) => ms >= card.slamMs - HUSH_MS && ms < card.endMs + CARD_OUT_MS) ?? null;

/** How white the frame flashes as a card slams in. */
export const flashAt = (card: RoundCard | null, ms: number): number => {
  if (!card) return 0;
  const since = ms - card.slamMs;
  return since < 0 ? 0 : (card.loud ? 0.14 : 0.05) * Math.max(0, 1 - since / 240);
};

const SHAKE_MS = 380;
const BREATH_MS = 18_000;

/** The camera: a slow breath in and out, a bounce on the battle's kicks, a shake as a battle's
 *  card slams in. Deterministic: the same frame always looks the same. */
export const cameraAt = (ms: number, groove: Groove | null, card: RoundCard | null): { scale: number; x: number; y: number } => {
  const breath = 0.006 * (1 - Math.cos((2 * Math.PI * ms) / BREATH_MS)) * 0.5;
  const bounce = groove ? 0.005 * groove.pulse * (groove.strong ? 1 : 0.4) : 0;
  let x = 0;
  let y = 0;
  const since = card?.loud ? ms - card.slamMs : -1;
  if (since >= 0 && since < SHAKE_MS) {
    const amp = 14 * (1 - since / SHAKE_MS) ** 2;
    x = amp * Math.sin(since / 11);
    y = amp * 0.6 * Math.cos(since / 13);
  }
  return { scale: 1 + breath + bounce, x, y };
};
