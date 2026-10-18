import { Audio } from '@remotion/media';
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline } from '../api/timeline';
import { Background } from './components/Background';
import { Captions } from './components/Captions';
import { BrandLockup, BrandMark, EndCard, RoundChip } from './components/Chrome';
import { SpeakerRowCard, SpeakingChip } from './components/SpeakerCard';
import { debaterTag } from './speakers';
import { DISPLAY_FONT, FONT, SHORT_HOOK_MS, SHORT_W, barHeight } from './constants';
import { frameToMs, highlightRange, msToFrame } from './utils';
import { SceneStage } from './visuals/SceneStage';

export interface ShortProps {
  timeline: Timeline;
  mediaBase: string;
  highlightIndex: number;
  [key: string]: unknown;
}

const HOST_COLOR = '#FFC46B';
// 9:16 layout (unit as in the mockup's phone frame): brand · speaker · round on top, debaters 1–2,
// the visual stage in the middle (round + question between scenes), debaters 3–4, then the
// captions, clear of the platform's UI at the bottom. With two debaters the stage takes the
// second row's place, so the captions stay where they are.
const U = (SHORT_W * 1.75) / 100;
const BAR_U = U * 0.9;
const X = 60;
const W = SHORT_W - 2 * X;
const GAP = 32;
const ROW_H = 140;
const ROW_W = (W - GAP) / 2;
const ROW_A_Y = 230;
const STAGE_Y = ROW_A_Y + ROW_H + GAP;
const STAGE_H = 760;
const STAGE_K = Math.min(W / 1160, STAGE_H / 700);
const ROW_B_Y = STAGE_Y + STAGE_H + GAP;
const CAPTIONS_Y = ROW_B_Y + ROW_H + 40;

export const DebateShort = ({ timeline, mediaBase, highlightIndex }: ShortProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const h = highlightRange(timeline, highlightIndex);
  const len = h.end_ms - h.start_ms;
  const localMs = frameToMs(frame, fps) - SHORT_HOOK_MS; // 0 = start of the highlight
  const absMs = h.start_ms + localMs;
  const inside = localMs >= 0 && localMs < len;
  const seg = inside ? (timeline.segments.find((s) => absMs >= s.start_ms && absMs < s.end_ms) ?? null) : null;
  // Between turns the last speaker keeps the chip.
  const current = seg ?? (inside ? ([...timeline.segments].reverse().find((s) => s.start_ms <= absMs) ?? null) : null);
  const speaker = current ? timeline.speakers.find((s) => s.id === current.speaker_id) : undefined;
  const debaters = timeline.speakers.filter((s) => s.role === 'debater');
  const inHook = localMs < 0;
  const inEnd = localMs >= len;
  // Segment times are absolute; the composition clock starts at the hook card.
  const offsetMs = SHORT_HOOK_MS - h.start_ms;
  const rows = [debaters.slice(0, 2), debaters.slice(2, 4)];
  const stageH = rows[1].length > 0 ? STAGE_H : ROW_B_Y + ROW_H - STAGE_Y;
  const row = (speakers: typeof debaters, y: number) => (
    <div style={{ position: 'absolute', top: y, left: X, width: W, display: 'flex', justifyContent: 'center', gap: GAP }}>
      {speakers.map((d) => (
        <SpeakerRowCard key={d.id} speaker={d} tag={debaterTag(d, debaters)} active={seg?.speaker_id === d.id} width={ROW_W} height={ROW_H} />
      ))}
    </div>
  );

  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <Background accent={speaker?.color ?? HOST_COLOR} />
      <Sequence from={msToFrame(SHORT_HOOK_MS)} durationInFrames={msToFrame(len) + 2} premountFor={fps}>
        <Audio src={`${mediaBase}/${timeline.full_audio_wav}`} trimBefore={msToFrame(h.start_ms)} trimAfter={msToFrame(h.end_ms)} />
      </Sequence>

      {inHook && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 70, textAlign: 'center', fontFamily: FONT, gap: 30, opacity: interpolate(frame / fps, [0, 0.3], [0, 1], { extrapolateRight: 'clamp' }) }}>
          <BrandLockup size={64} />
          <div style={{ fontFamily: DISPLAY_FONT, fontSize: 80, fontWeight: 800, letterSpacing: -2.4, color: '#F2F3F7', lineHeight: 1.08 }}>{h.hook}</div>
          <div style={{ fontSize: 36, color: '#ffffffb3', fontWeight: 600 }}>
            {debaters.map((d, i) => (
              <span key={d.id}>
                {i > 0 && ' vs '}
                <span style={{ color: d.color }}>{d.name}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {!inHook && !inEnd && (
        <div style={{ position: 'absolute', inset: 0, opacity: interpolate(localMs, [0, 400], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }) }}>
          <div style={{ position: 'absolute', top: 2.2 * U, left: 2.4 * U, right: 2.4 * U, height: barHeight(BAR_U), display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <BrandMark u={BAR_U} />
            <div>{current && <RoundChip roundId={current.round_id} u={BAR_U} />}</div>
          </div>
          {speaker && (
            <div style={{ position: 'absolute', top: 2.2 * U, left: 0, right: 0, height: barHeight(BAR_U), display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <SpeakingChip speaker={speaker} seg={seg} offsetMs={offsetMs} u={BAR_U} />
            </div>
          )}
          {row(rows[0], ROW_A_Y)}
          <SceneStage timeline={timeline} mediaBase={mediaBase} seg={current} ms={absMs} x={X} y={STAGE_Y} w={W} h={stageH} k={STAGE_K} />
          {rows[1].length > 0 && row(rows[1], ROW_B_Y)}
          <div style={{ position: 'absolute', left: 3 * U, right: 3 * U, top: CAPTIONS_Y, height: 330, display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
            <Captions seg={seg} offsetMs={offsetMs} fontSize={2.8 * U} maxWidth={SHORT_W - 6 * U} combineMs={900} />
          </div>
        </div>
      )}

      {inEnd && <EndCard big={false} text="Who won? Full debate on the channel" sinceMs={localMs - len} />}
    </AbsoluteFill>
  );
};
