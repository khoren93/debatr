import { Audio } from '@remotion/media';
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline } from '../api/timeline';
import { Background } from './components/Background';
import { Captions } from './components/Captions';
import { EndCard } from './components/Chrome';
import { SpeakerCard } from './components/SpeakerCard';
import { ACCENT, FONT, SHORT_HOOK_MS } from './constants';
import { frameToMs, highlightRange, msToFrame } from './utils';
import { SceneStage } from './visuals/SceneStage';

export interface ShortProps {
  timeline: Timeline;
  mediaBase: string;
  highlightIndex: number;
  [key: string]: unknown;
}

// 9:16 layout: topic line, row of debaters, the visual stage, captions, progress bar.
const STAGE = { x: 60, y: 590, w: 960, h: 680 };
const STAGE_K = Math.min(STAGE.w / 1160, STAGE.h / 700);
const CARD_W: Record<number, number> = { 1: 320, 2: 320, 3: 290, 4: 228 };

export const DebateShort = ({ timeline, mediaBase, highlightIndex }: ShortProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const h = highlightRange(timeline, highlightIndex);
  const len = h.end_ms - h.start_ms;
  const localMs = frameToMs(frame, fps) - SHORT_HOOK_MS; // 0 = start of the highlight
  const absMs = h.start_ms + localMs;
  const seg = localMs >= 0 && localMs < len ? timeline.segments.find((s) => absMs >= s.start_ms && absMs < s.end_ms) ?? null : null;
  const active = seg ? timeline.speakers.find((s) => s.id === seg.speaker_id) : null;
  const debaters = timeline.speakers.filter((s) => s.role === 'debater');
  const accent = active?.color ?? ACCENT;
  const inHook = localMs < 0;
  const inEnd = localMs >= len;
  const progress = Math.max(0, Math.min(1, localMs / len));
  // Segment times are absolute; the composition clock starts at the hook card.
  const offsetMs = SHORT_HOOK_MS - h.start_ms;
  const cardWidth = CARD_W[debaters.length] ?? 228;

  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <Background accent={accent} />
      <Sequence from={msToFrame(SHORT_HOOK_MS)} durationInFrames={msToFrame(len) + 2} premountFor={fps}>
        <Audio src={`${mediaBase}/${timeline.full_audio_wav}`} trimBefore={msToFrame(h.start_ms)} trimAfter={msToFrame(h.end_ms)} />
      </Sequence>

      {inHook && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 70, textAlign: 'center', fontFamily: FONT, gap: 30, opacity: interpolate(frame / fps, [0, 0.3], [0, 1], { extrapolateRight: 'clamp' }) }}>
          <div style={{ fontSize: 30, letterSpacing: 8, color: ACCENT, fontWeight: 800 }}>DEBATR</div>
          <div style={{ fontSize: 80, fontWeight: 900, color: '#fff', lineHeight: 1.08 }}>{h.hook}</div>
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
        <>
          <div style={{ position: 'absolute', top: 64, left: 0, right: 0, textAlign: 'center', fontFamily: FONT, opacity: interpolate(localMs, [0, 400], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }) }}>
            <div style={{ fontSize: 24, letterSpacing: 8, color: ACCENT, fontWeight: 800 }}>DEBATR</div>
            <div style={{ fontSize: 36, fontWeight: 800, color: '#fff', padding: '6px 60px', lineHeight: 1.15 }}>{timeline.topic}</div>
          </div>
          <div style={{ position: 'absolute', top: 236, left: 0, right: 0, display: 'flex', justifyContent: 'center', gap: 24 }}>
            {debaters.map((d) => (
              <SpeakerCard key={d.id} speaker={d} seg={seg} offsetMs={offsetMs} active={active?.id === d.id} width={cardWidth} compact />
            ))}
          </div>
          <SceneStage timeline={timeline} mediaBase={mediaBase} seg={seg} ms={absMs} x={STAGE.x} y={STAGE.y} w={STAGE.w} h={STAGE.h} k={STAGE_K} />
          <div style={{ position: 'absolute', left: 0, right: 0, top: 1300, height: 440, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Captions seg={seg} offsetMs={offsetMs} color={accent} fontSize={72} maxWidth={1000} combineMs={900} />
          </div>
          <div style={{ position: 'absolute', left: 60, right: 60, bottom: 110, height: 12, borderRadius: 6, background: '#ffffff22' }}>
            <div style={{ width: `${progress * 100}%`, height: '100%', borderRadius: 6, background: accent }} />
          </div>
        </>
      )}

      {inEnd && <EndCard big={false} text="Who won? Full debate on the channel" sinceMs={localMs - len} />}
    </AbsoluteFill>
  );
};
