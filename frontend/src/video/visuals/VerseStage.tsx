import type { Timeline, TimelineSegment } from '../../api/timeline';
import { ModelLogo } from '../components/ModelLogo';
import { ACCENT, DISPLAY_FONT, MONO_FONT } from '../constants';
import { lineAt, verseLines, type LyricLine } from '../lyrics';
import { speakerModelId } from '../speakers';
import { roundLabel } from '../utils';
import { INK, backOut, easeOut, fitFont, ramp } from './draw';

/** A line comes up this long before its first word, so the eye is there when it is rapped. */
const LEAD_MS = 140;
const ENTER_MS = 260;
const POP_MS = 220;
/** The rapper's name opens the verse only when the beat leaves room before the first line. */
const TITLE_MIN_MS = 700;
const HOST = '#FFC46B';
const AHEAD = 'rgba(242,243,247,0.3)';

/** A line's words: rapped ones white, the current one in the accent and popping, the ones ahead
 *  dim; the last word in the rapper's colour, underlined in the accent when it rhymes. A line
 *  already rapped (`live` off) shows everything said. */
const Words = ({ line, ms, size, color, live }: { line: LyricLine; ms: number; size: number; color: string; live: boolean }) => {
  const last = line.words.length - 1;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'baseline', columnGap: '0.3em', rowGap: size * 0.1, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: size, lineHeight: 1.12, letterSpacing: -0.02 * size, textAlign: 'center' }}>
      {line.words.map((word, i) => {
        const said = !live || ms >= word.fromMs;
        const now = live && said && ms < word.toMs;
        const end = i === last;
        const pop = live && said ? 1 - easeOut(ramp(ms, word.fromMs, POP_MS)) : 0;
        const fill = !said ? AHEAD : now ? ACCENT : end ? color : INK;
        return (
          <span key={i} style={{ position: 'relative', display: 'inline-block', color: fill, transform: `translateY(${-0.08 * size * pop}px) scale(${1 + 0.1 * pop})`, transformOrigin: '50% 80%' }}>
            {word.text}
            {end && line.rhymes && said && (
              <span style={{ position: 'absolute', left: 0, right: 0, bottom: -0.04 * size, height: Math.max(3, 0.07 * size), borderRadius: size, background: ACCENT, transform: `scaleX(${live ? easeOut(ramp(ms, word.fromMs, 300)) : 1})`, transformOrigin: 'left center' }} />
            )}
          </span>
        );
      })}
    </div>
  );
};

/** The stage during a rap verse: the line being rapped big in the middle, the one before it
 *  small above, the rapper's logo faint behind (thumping with `pulse`, the beat); before the
 *  first line, the rapper's name. A tall
 *  box (the Short) takes bigger type over up to four lines, closer to the middle. */
export const VerseStage = ({ timeline, seg, ms, w, h, k, pulse = 0 }: { timeline: Timeline; seg: TimelineSegment; ms: number; w: number; h: number; k: number; pulse?: number }) => {
  const lines = verseLines(seg);
  const speaker = timeline.speakers.find((s) => s.id === seg.speaker_id);
  const color = speaker?.color ?? ACCENT;
  const at = lineAt(lines, ms + LEAD_MS);
  const line = at >= 0 ? lines[at] : null;
  const prev = at > 0 ? lines[at - 1] : null;
  const pad = w * 0.06;
  const tall = h > w * 0.9;
  const big = tall ? fitFont(line?.text ?? '', w - 2 * pad, 4, 112 * k, 56 * k) : fitFont(line?.text ?? '', w - 2 * pad, 2, 78 * k, 44 * k);
  const small = tall ? fitFont(prev?.text ?? '', w - 2 * pad, 2, 46 * k, 32 * k) : fitFont(prev?.text ?? '', w - 2 * pad, 2, 36 * k, 26 * k);
  const prevBox = tall ? { top: h * 0.12, height: h * 0.27 } : { top: h * 0.07, height: h * 0.25 };
  const lineBox = tall ? { top: h * 0.42, bottom: h * 0.2 } : { top: h * 0.36, bottom: h * 0.08 };
  const enter = line ? easeOut(ramp(ms, line.startMs - LEAD_MS, ENTER_MS)) : 0;
  const first = lines[0];
  const titled = Boolean(speaker && first && first.startMs - seg.start_ms >= TITLE_MIN_MS);
  const title = titled && first ? backOut(ramp(ms, seg.start_ms, 420)) * (1 - ramp(ms, first.startMs - LEAD_MS - 200, 200)) : 0;
  const nameSize = speaker ? fitFont(speaker.name, w * 0.8, 1, 112 * k, 60 * k) : 0;
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden' }}>
      {speaker && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 0.07 + 0.05 * pulse, transform: `scale(${1 + 0.05 * pulse})` }}>
          <ModelLogo modelId={speakerModelId(speaker)} size={h * 0.62} color={color} />
        </div>
      )}
      {title > 0 && speaker && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 18 * k, opacity: Math.min(1, title), transform: `scale(${0.85 + 0.15 * title})` }}>
          <div style={{ fontFamily: MONO_FONT, fontSize: 23 * k, letterSpacing: 0.3 * 23 * k, color: HOST }}>{roundLabel(seg.round_id, seg.round_label).toUpperCase()}</div>
          <div style={{ fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: nameSize, lineHeight: 1, letterSpacing: -0.03 * nameSize, color, whiteSpace: 'nowrap' }}>{speaker.name}</div>
        </div>
      )}
      {prev && line && (
        <div style={{ position: 'absolute', left: pad, right: pad, ...prevBox, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', opacity: 0.42 * enter }}>
          <Words line={prev} ms={ms} size={small} color={color} live={false} />
        </div>
      )}
      {line && (
        <div style={{ position: 'absolute', left: pad, right: pad, ...lineBox, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: enter, transform: `translateY(${(1 - enter) * 36 * k}px)` }}>
          <Words line={line} ms={ms} size={big} color={color} live />
        </div>
      )}
    </div>
  );
};
