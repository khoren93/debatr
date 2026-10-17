import { useCurrentFrame, useVideoConfig } from 'remotion';
import type { TimelineSegment } from '../../api/timeline';
import { ACCENT, DISPLAY_FONT } from '../constants';
import { captionPages, frameToMs } from '../utils';

/** Karaoke captions on a dark plate: the current word in the accent, the said ones white. */
export const Captions = ({ seg, offsetMs, fontSize, maxWidth, combineMs = 1200 }: { seg: TimelineSegment | null; offsetMs: number; fontSize: number; maxWidth: number; combineMs?: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = frameToMs(frame, fps) - offsetMs;
  if (!seg) return null;
  const pages = captionPages(seg, combineMs);
  const page = pages.find((p) => ms >= p.startMs && ms < p.startMs + p.durationMs) ?? (ms >= seg.end_ms - 400 ? pages[pages.length - 1] : null);
  if (!page) return null;
  return (
    <div style={{ maxWidth, display: 'flex', flexWrap: 'wrap', justifyContent: 'center', columnGap: '0.28em', padding: `${fontSize * 0.375}px ${fontSize * 0.83}px`, borderRadius: fontSize * 0.58, background: 'rgba(8,9,13,0.78)', fontFamily: DISPLAY_FONT, fontWeight: 700, fontSize, lineHeight: 1.25, textAlign: 'center' }}>
      {page.tokens.map((t, i) => {
        const now = ms >= t.fromMs && ms < t.toMs;
        const spoken = ms >= t.toMs;
        return (
          <span key={i} style={{ color: now ? ACCENT : spoken ? '#F2F3F7' : 'rgba(242,243,247,0.5)' }}>
            {t.text.trim()}
          </span>
        );
      })}
    </div>
  );
};
