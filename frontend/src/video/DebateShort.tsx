import { Audio } from '@remotion/media';
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline } from '../api/timeline';
import { timelineFormat } from '../lib/formats';
import { Background } from './components/Background';
import { Captions } from './components/Captions';
import { SfxTrack } from './components/Sfx';
import { BrandMark, EndCard, LabelChip, RoundChip } from './components/Chrome';
import { FaceOff } from './components/FaceOff';
import { SpeakerRowCard, SpeakingChip } from './components/SpeakerCard';
import { debaterTag } from './speakers';
import { ACCENT, DISPLAY_FONT, FONT, SHORT_H, SHORT_HOOK_MS, SHORT_W, barHeight, headlineSize } from './constants';
import { cameraAt, flashAt, glowColorAt, grooveAt, roundCardAt } from './groove';
import { hitAt } from './moments';
import { frameToMs, highlightRange, levelAt, msToFrame } from './utils';
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
// captions, clear of the platform's UI at the bottom. The stage's box is centred in the frame;
// debaters 3–4 take its lower part, so the rows and the captions stay where they are.
const U = (SHORT_W * 1.75) / 100;
const BAR_U = U * 0.9;
const X = 60;
const W = SHORT_W - 2 * X;
const GAP = 32;
const ROW_H = 140;
const ROW_W = (W - GAP) / 2;
const STAGE_Y = SHORT_H / 2 - 525;
const STAGE_END = SHORT_H - STAGE_Y;
const ROW_A_Y = STAGE_Y - GAP - ROW_H;
const ROW_B_Y = STAGE_END - ROW_H;
const STAGE_H = ROW_B_Y - GAP - STAGE_Y;
const STAGE_K = Math.min(W / 1160, STAGE_H / 700);
const CAPTIONS_Y = STAGE_END + 36;
// A rap verse's lines (no captions then) reach down to here, clear of the platform's UI.
const VERSE_BOTTOM = SHORT_H - 300;

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
  const stageH = rows[1].length > 0 ? STAGE_H : STAGE_END - STAGE_Y;
  // A battle moves on its beat (lights, logos, the camera's bounce); a debate's logo on the voice.
  const groove = timelineFormat(timeline).id === 'rap_battle' ? grooveAt(timeline, current, absMs) : null;
  const pulse = groove ? groove.pulse * (groove.strong ? 1 : 0.5) : 0.6 * levelAt(seg, absMs);
  const card = inside ? roundCardAt(timeline, absMs) : null;
  // A line that lands (punchline / zinger) pushes the camera in, flashes, shakes a battle.
  const hit = !inside ? null : hitAt(timeline, absMs);
  const base = cameraAt(absMs, groove, card);
  const cam = { scale: base.scale + (hit?.push ?? 0), x: base.x + (hit?.shake.x ?? 0), y: base.y + (hit?.shake.y ?? 0) };
  const flash = Math.min(0.25, flashAt(card, absMs) + (hit?.flash ?? 0));
  const flinchOf = (id: string) => (hit && hit.moment.kind === 'punchline' && hit.moment.speaker_id !== id ? hit.flinch : 0);
  const lights = groove && debaters.length >= 2 ? { colors: [debaters[0].color, debaters[1].color] as [string, string], active: speaker?.role === 'debater' ? speaker.color : null, groove } : null;
  const row = (speakers: typeof debaters, y: number) => (
    <div style={{ position: 'absolute', top: y, left: X, width: W, display: 'flex', justifyContent: 'center', gap: GAP }}>
      {speakers.map((d) => (
        <SpeakerRowCard key={d.id} speaker={d} tag={debaterTag(d, debaters)} active={seg?.speaker_id === d.id} width={ROW_W} height={ROW_H} pulse={pulse} flinch={flinchOf(d.id)} />
      ))}
    </div>
  );

  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <Background accent={glowColorAt(timeline, absMs, HOST_COLOR)} ms={absMs} lights={lights} />
      <Sequence from={msToFrame(SHORT_HOOK_MS)} durationInFrames={msToFrame(len) + 2} premountFor={fps}>
        <Audio src={`${mediaBase}/${timeline.full_audio_wav}`} trimBefore={msToFrame(h.start_ms)} trimAfter={msToFrame(h.end_ms)} />
      </Sequence>
      <SfxTrack timeline={timeline} offsetMs={SHORT_HOOK_MS - h.start_ms} fromMs={h.start_ms} toMs={h.end_ms} />

      {/* The hook card: the face-off with the clip's hook line, fully drawn on frame 0. */}
      {inHook && (
        <div style={{ position: 'absolute', inset: 0, fontFamily: FONT, opacity: interpolate(frame / fps, [SHORT_HOOK_MS / 1000 - 0.3, SHORT_HOOK_MS / 1000], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }) }}>
          <FaceOff debaters={debaters} width={SHORT_W} height={SHORT_H} logoY={0.3} logoSize={230} t={frame / fps} length={SHORT_HOOK_MS / 1000} />
          <div style={{ position: 'absolute', top: 2.2 * U, left: 2.4 * U, right: 2.4 * U, height: barHeight(BAR_U), display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <BrandMark u={BAR_U} />
            <LabelChip label={timelineFormat(timeline).label} u={BAR_U} color={ACCENT} />
          </div>
          <div style={{ position: 'absolute', left: X, right: X, top: SHORT_H * 0.5, bottom: SHORT_H * 0.12, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
            <div style={{ fontFamily: DISPLAY_FONT, fontSize: headlineSize(h.hook, 80), fontWeight: 800, letterSpacing: -0.03 * headlineSize(h.hook, 80), color: '#F2F3F7', lineHeight: 1.08 }}>{h.hook}</div>
          </div>
        </div>
      )}

      {!inHook && !inEnd && (
        <div style={{ position: 'absolute', inset: 0, opacity: interpolate(localMs, [0, 400], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }), transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.scale})` }}>
          <div style={{ position: 'absolute', top: 2.2 * U, left: 2.4 * U, right: 2.4 * U, height: barHeight(BAR_U), display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <BrandMark u={BAR_U} />
            <div>{current && <RoundChip roundId={current.round_id} label={current.round_label} u={BAR_U} />}</div>
          </div>
          {speaker && (
            <div style={{ position: 'absolute', top: 2.2 * U, left: 0, right: 0, height: barHeight(BAR_U), display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <SpeakingChip speaker={speaker} seg={seg} offsetMs={offsetMs} u={BAR_U} />
            </div>
          )}
          {row(rows[0], ROW_A_Y)}
          <SceneStage timeline={timeline} mediaBase={mediaBase} seg={current} ms={absMs} x={X} y={STAGE_Y} w={W} h={stageH} k={STAGE_K} verseExtend={VERSE_BOTTOM - STAGE_Y - stageH} card={card} pulse={groove ? pulse : 0} />
          {rows[1].length > 0 && row(rows[1], ROW_B_Y)}
          <div style={{ position: 'absolute', left: 3 * U, right: 3 * U, top: CAPTIONS_Y, height: SHORT_H - CAPTIONS_Y - 60, display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
            {seg?.turn_type !== 'verse' && <Captions seg={seg} offsetMs={offsetMs} fontSize={2.8 * U} maxWidth={SHORT_W - 6 * U} combineMs={900} moment={hit?.moment} />}
          </div>
        </div>
      )}

      {flash > 0 && <AbsoluteFill style={{ background: '#FFFFFF', opacity: flash }} />}
      {inEnd && <EndCard big={false} text="Who won? Full debate on the channel" sinceMs={localMs - len} />}
    </AbsoluteFill>
  );
};
