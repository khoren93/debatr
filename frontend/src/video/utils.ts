import { createTikTokStyleCaptions, type Caption, type TikTokPage } from '@remotion/captions';
import type { Timeline, TimelineSegment } from '../api/timeline';
import { FPS, INTRO_MS, OUTRO_MS, SHORT_END_MS, SHORT_HOOK_MS } from './constants';

export const msToFrame = (ms: number, fps = FPS): number => Math.round((ms / 1000) * fps);
export const frameToMs = (frame: number, fps = FPS): number => (frame / fps) * 1000;

export const longDurationInFrames = (t: Timeline): number => msToFrame(INTRO_MS + t.total_ms + OUTRO_MS);

export const highlightRange = (t: Timeline, index: number) => {
  const h = t.highlights[index] ?? t.highlights[0];
  if (h) return { start_ms: h.start_ms, end_ms: h.end_ms, hook: h.hook, title: h.title };
  return { start_ms: 0, end_ms: Math.min(t.total_ms, 45_000), hook: t.topic, title: t.title };
};

export const shortDurationInFrames = (t: Timeline, index: number): number => {
  const h = highlightRange(t, index);
  return msToFrame(SHORT_HOOK_MS + (h.end_ms - h.start_ms) + SHORT_END_MS);
};

export const segmentAt = (t: Timeline, ms: number): TimelineSegment | null =>
  t.segments.find((s) => ms >= s.start_ms && ms < s.end_ms) ?? null;

/** The segment being spoken, or the last one before `ms` during a pause between turns. */
export const speakingAt = (t: Timeline, ms: number): TimelineSegment | null => {
  let last: TimelineSegment | null = null;
  for (const s of t.segments) {
    if (s.start_ms > ms) break;
    last = s;
  }
  return last;
};

/** Loudness of a segment at an absolute time, 0..1 (interpolated). */
export const levelAt = (seg: TimelineSegment | null, ms: number): number => {
  if (!seg || seg.levels.length === 0) return 0;
  const rel = ms - seg.start_ms;
  const pos = (rel / 1000) * seg.levels_hz;
  const i = Math.floor(pos);
  const clamp = (n: number) => Math.max(0, Math.min(seg.levels.length - 1, n));
  const a = seg.levels[clamp(i)] ?? 0;
  const b = seg.levels[clamp(i + 1)] ?? a;
  return a + (b - a) * (pos % 1);
};

const pagesCache = new WeakMap<TimelineSegment, Map<number, TikTokPage[]>>();

/** TikTok-style caption pages for a segment (absolute times). */
export const captionPages = (seg: TimelineSegment, combineMs: number): TikTokPage[] => {
  let perSeg = pagesCache.get(seg);
  if (!perSeg) {
    perSeg = new Map();
    pagesCache.set(seg, perSeg);
  }
  const cached = perSeg.get(combineMs);
  if (cached) return cached;
  const captions: Caption[] = seg.words.map((w) => ({
    text: ` ${w.w}`,
    startMs: seg.start_ms + w.s,
    endMs: seg.start_ms + Math.max(w.e, w.s + 40),
    timestampMs: null,
    confidence: null,
  }));
  const { pages } = createTikTokStyleCaptions({ captions, combineTokensWithinMilliseconds: combineMs });
  perSeg.set(combineMs, pages);
  return pages;
};

export const roundLabel = (roundId: string): string =>
  roundId === 'verdict' ? 'Verdict' : roundId.replace(/^round_(\d+)$/, 'Round $1');

/** Display size that keeps a headline within about three lines. */
export const headlineSize = (text: string, base: number) => (text.length <= 60 ? base : text.length <= 100 ? base * 0.84 : base * 0.7);
