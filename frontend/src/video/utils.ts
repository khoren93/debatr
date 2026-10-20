import { createTikTokStyleCaptions, type Caption, type TikTokPage } from '@remotion/captions';
import type { TimelineSegment } from '../api/timeline';

export * from './timing';

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

/** The segment's own label from the format, else derived from the round id (older timelines). */
export const roundLabel = (roundId: string, label?: string | null): string =>
  label || (roundId === 'verdict' ? 'Verdict' : roundId.replace(/^round_(\d+)$/, 'Round $1'));

/** Display size that keeps a headline within about three lines. */
export const headlineSize = (text: string, base: number) => (text.length <= 60 ? base : text.length <= 100 ? base * 0.84 : base * 0.7);
