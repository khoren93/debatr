import { Audio } from '@remotion/media';
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline } from '../api/timeline';
import { Background } from './components/Background';
import { Captions } from './components/Captions';
import { BrandMark, EndCard, RoundChip } from './components/Chrome';
import { SpeakerCard, SpeakingChip } from './components/SpeakerCard';
import { debaterTag } from './speakers';
import { ACCENT, BRAND, DISPLAY_FONT, FONT, MONO_FONT, SHORT_HOOK_MS, SHORT_W } from './constants';
import { frameToMs, highlightRange, msToFrame } from './utils';
import { SceneStage } from './visuals/SceneStage';

export interface ShortProps {
  timeline: Timeline;
  mediaBase: string;
  highlightIndex: number;
  [key: string]: unknown;
}

const HOST_COLOR = '#FFC46B';
// 9:16 layout (unit as in the mockup's phone frame): round · speaker · brand on top, the visual
// stage (round + question between scenes), the debaters' cards, captions above the platform UI.
const U = (SHORT_W * 1.75) / 100;
const STAGE = { x: 60, y: 170, w: 960, h: 680 };
const STAGE_K = Math.min(STAGE.w / 1160, STAGE.h / 700);
const CARDS_Y = 880;
const CARD_W: Record<number, number> = { 1: 17 * U, 2: 17 * U, 3: 290, 4: 228 };

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
  const cardWidth = CARD_W[debaters.length] ?? 228;

  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <Background accent={speaker?.color ?? HOST_COLOR} />
      <Sequence from={msToFrame(SHORT_HOOK_MS)} durationInFrames={msToFrame(len) + 2} premountFor={fps}>
        <Audio src={`${mediaBase}/${timeline.full_audio_wav}`} trimBefore={msToFrame(h.start_ms)} trimAfter={msToFrame(h.end_ms)} />
      </Sequence>

      {inHook && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 70, textAlign: 'center', fontFamily: FONT, gap: 30, opacity: interpolate(frame / fps, [0, 0.3], [0, 1], { extrapolateRight: 'clamp' }) }}>
          <div style={{ fontFamily: MONO_FONT, fontSize: 30, letterSpacing: 8, color: ACCENT }}>{BRAND}</div>
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
          <div style={{ position: 'absolute', top: 2.2 * U, left: 2.4 * U, right: 2.4 * U, height: 3.8 * U, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>{current && <RoundChip roundId={current.round_id} u={U} />}</div>
            <BrandMark u={U} />
          </div>
          {speaker && (
            <div style={{ position: 'absolute', top: 2.2 * U, left: 0, right: 0, height: 3.8 * U, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <SpeakingChip speaker={speaker} seg={seg} offsetMs={offsetMs} u={U * 0.9} />
            </div>
          )}
          <SceneStage timeline={timeline} mediaBase={mediaBase} seg={current} ms={absMs} x={STAGE.x} y={STAGE.y} w={STAGE.w} h={STAGE.h} k={STAGE_K} idleAlign="end" />
          <div style={{ position: 'absolute', top: CARDS_Y, left: 0, right: 0, display: 'flex', justifyContent: 'center', gap: 2 * U }}>
            {debaters.map((d) => (
              <SpeakerCard key={d.id} speaker={d} tag={debaterTag(d, debaters)} active={seg?.speaker_id === d.id} width={cardWidth} />
            ))}
          </div>
          <div style={{ position: 'absolute', left: 3 * U, right: 3 * U, top: 1210, height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Captions seg={seg} offsetMs={offsetMs} fontSize={2.8 * U} maxWidth={SHORT_W - 6 * U} combineMs={900} />
          </div>
        </div>
      )}

      {inEnd && <EndCard big={false} text="Who won? Full debate on the channel" sinceMs={localMs - len} />}
    </AbsoluteFill>
  );
};
