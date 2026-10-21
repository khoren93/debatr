import type { Timeline, TimelineSegment } from '../../api/timeline';
import { ModelLogo } from '../components/ModelLogo';
import { ACCENT, DISPLAY_FONT, MONO_FONT } from '../constants';
import { balanceRows, lineAt, verseLines, type LyricLine } from '../lyrics';
import { hitAt, inMoment } from '../moments';
import type { TimelineMoment } from '../../api/timeline';
import { speakerModelId } from '../speakers';
import { roundLabel } from '../utils';
import { INK, backOut, easeOut, fitFont, ramp, rowsAt } from './draw';

/** A line comes up this long before its first word, so the eye is there when it is rapped. */
const LEAD_MS = 140;
const ENTER_MS = 260;
/** As a line comes up, the one before lifts away this fast and the new one enters this much
 *  later, so the two do not cross. */
const LEAVE_MS = 120;
const TURN_DELAY_MS = 80;
const POP_MS = 220;
/** A punchline that just landed holds the stage this long before the next line comes up (the
 *  rapper is already on it; its words catch up). */
const PUNCH_HOLD_MS = 450;
/** The rapper's name opens the verse only when the beat leaves room before the first line. */
const TITLE_MIN_MS = 700;
const HOST = '#FFC46B';
const AHEAD = 'rgba(242,243,247,0.3)';

/** A line's words: rapped ones white, the current one in the accent and popping, the ones ahead
 *  dim; the last word in the rapper's colour, underlined in the accent when it rhymes. Once a
 *  punchline (`punch`) lands, its words turn to the accent. Broken into `rows` even rows (each
 *  still wraps if it must). */
const Words = ({ line, ms, size, color, punch = null, rows = 1 }: { line: LyricLine; ms: number; size: number; color: string; punch?: TimelineMoment | null; rows?: number }) => {
  const landed = punch !== null && ms >= punch.end_ms;
  const last = line.words.length - 1;
  const counts = balanceRows(
    line.words.map((word) => word.text),
    rows,
  );
  const starts = counts.map((_, r) => counts.slice(0, r).reduce((sum, n) => sum + n, 0));
  const word = (i: number) => {
    const { text, fromMs, toMs } = line.words[i];
    const said = ms >= fromMs;
    const now = said && ms < toMs;
    const end = i === last;
    const pop = said ? 1 - easeOut(ramp(ms, fromMs, POP_MS)) : 0;
    const fill = !said ? AHEAD : now || (landed && inMoment(punch, fromMs, toMs)) ? ACCENT : end ? color : INK;
    return (
      <span key={i} style={{ position: 'relative', display: 'inline-block', color: fill, transform: `translateY(${-0.08 * size * pop}px) scale(${1 + 0.1 * pop})`, transformOrigin: '50% 80%' }}>
        {text}
        {end && line.rhymes && said && (
          <span style={{ position: 'absolute', left: 0, right: 0, bottom: -0.04 * size, height: Math.max(3, 0.07 * size), borderRadius: size, background: ACCENT, transform: `scaleX(${easeOut(ramp(ms, fromMs, 300))})`, transformOrigin: 'left center' }} />
        )}
      </span>
    );
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', rowGap: size * 0.1, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: size, lineHeight: 1.12, letterSpacing: -0.02 * size, textAlign: 'center' }}>
      {counts.map((count, r) => (
        <div key={r} style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'baseline', columnGap: '0.3em', rowGap: size * 0.1 }}>
          {Array.from({ length: count }, (_, j) => word(starts[r] + j))}
        </div>
      ))}
    </div>
  );
};

/** The stage during a rap verse: the line being rapped big in the middle, alone — the one before
 *  lifts away as it comes up —, the rapper's logo faint behind (thumping with `pulse`, the beat);
 *  before the first line, the rapper's name. A tall box (the Short) takes bigger type. */
export const VerseStage = ({ timeline, seg, ms, w, h, k, pulse = 0 }: { timeline: Timeline; seg: TimelineSegment; ms: number; w: number; h: number; k: number; pulse?: number }) => {
  const lines = verseLines(seg);
  const speaker = timeline.speakers.find((s) => s.id === seg.speaker_id);
  const color = speaker?.color ?? ACCENT;
  const hit = hitAt(timeline, ms);
  const verseHit = hit && hit.moment.seq_index === seg.seq_index ? hit.moment : null;
  const landsAt = verseHit?.end_ms ?? 0;
  // The line ending on the punchline that just landed.
  const punchLine = (i: number) => verseHit !== null && lines[i].endMs >= landsAt - 30 && lines[i].startMs <= landsAt;
  // When line i comes up: just before its first word, or after the punchline's hold before it.
  const shownAt = (i: number) => (i > 0 && punchLine(i - 1) ? Math.max(lines[i].startMs, landsAt + PUNCH_HOLD_MS) : lines[i].startMs) - LEAD_MS;
  let at = lineAt(lines, ms + LEAD_MS);
  if (at > 0 && ms < shownAt(at)) at -= 1;
  const pad = w * 0.06;
  const width = w - 2 * pad;
  const tall = h > w * 0.9;
  const box = { top: h * 0.08, bottom: h * 0.08 };
  const leave = at > 0 ? easeOut(ramp(ms, shownAt(at), LEAVE_MS)) : 1;
  const enter = at >= 0 ? easeOut(ramp(ms, shownAt(at) + (at > 0 ? TURN_DELAY_MS : 0), ENTER_MS)) : 0;
  const first = lines[0];
  const titled = Boolean(speaker && first && first.startMs - seg.start_ms >= TITLE_MIN_MS);
  const title = titled && first ? backOut(ramp(ms, seg.start_ms, 420)) * (1 - ramp(ms, first.startMs - LEAD_MS - 200, 200)) : 0;
  const nameSize = speaker ? fitFont(speaker.name, w * 0.8, 1, 112 * k, 60 * k) : 0;
  // A punchline slams into place as its last word lands.
  const punchOf = (i: number) => (i >= 0 && punchLine(i) ? verseHit : null);
  const punch = punchOf(at);
  const slam = punch && hit && ms >= punch.end_ms ? 1 + 0.1 * (1 - easeOut(hit.landed)) : 1;
  const line = (i: number, punch: TimelineMoment | null) => {
    const size = tall ? fitFont(lines[i].text, width, 4, 112 * k, 56 * k) : fitFont(lines[i].text, width, 2, 78 * k, 44 * k);
    return <Words line={lines[i]} ms={ms} size={size} color={color} punch={punch} rows={rowsAt(lines[i].text, size, width)} />;
  };
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
      {leave < 1 && (
        <div style={{ position: 'absolute', left: pad, right: pad, ...box, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 1 - leave, transform: `translateY(${-leave * 48 * k}px)` }}>
          {line(at - 1, punchOf(at - 1))}
        </div>
      )}
      {at >= 0 && (
        <div style={{ position: 'absolute', left: pad, right: pad, ...box, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: enter, transform: `translateY(${(1 - enter) * 36 * k}px) scale(${slam})` }}>
          {line(at, punch)}
        </div>
      )}
    </div>
  );
};
