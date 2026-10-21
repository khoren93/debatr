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

