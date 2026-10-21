import { Audio } from '@remotion/media';
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline, TimelineSpeaker } from '../api/timeline';
import { timelineFormat } from '../lib/formats';
import { Background } from './components/Background';
import { Captions } from './components/Captions';
import { BrandMark, EndCard, IntroCard, RoundChip, VerdictCard } from './components/Chrome';
import { SpeakerCard, SpeakingChip } from './components/SpeakerCard';
import { debaterTag } from './speakers';
import { INTRO_MS, LONG_W, barHeight } from './constants';
import { cameraAt, flashAt, glowColorAt, grooveAt, roundCardAt } from './groove';
import { frameToMs, levelAt, msToFrame, segmentAt, speakingAt } from './utils';
import { SceneStage } from './visuals/SceneStage';

export interface DebateProps {
  timeline: Timeline;
  mediaBase: string; // absolute URL of the debate's media folder
  [key: string]: unknown;
}

const VERDICT_LEAD_MS = 2200;
const HOST_COLOR = '#FFC46B';
// Studio layout (unit = 1% of the width, as in the mockup): brand · speaker · round on top,
// debaters in side columns, the visual stage in the middle, captions at the bottom.
const U = LONG_W / 100;
const STAGE = { x: 380, y: 160, w: 1160, h: 690 };
const SIDE_X = 3 * U;
const SIDE_W = STAGE.x - SIDE_X - 24;

const SideColumn = ({ speakers, debaters, x, activeId, pulse }: { speakers: TimelineSpeaker[]; debaters: TimelineSpeaker[]; x: number; activeId: string | undefined; pulse: number }) => (
  <div style={{ position: 'absolute', left: x, top: STAGE.y, width: SIDE_W, height: STAGE.h, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 28 }}>
    {speakers.map((d) => (
      <SpeakerCard key={d.id} speaker={d} tag={debaterTag(d, debaters)} active={activeId === d.id} width={speakers.length > 1 ? Math.min(SIDE_W, 250) : SIDE_W - 8} pulse={pulse} />
    ))}
  </div>
);

export const DebateLong = ({ timeline, mediaBase }: DebateProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = frameToMs(frame, fps) - INTRO_MS;
  const seg = segmentAt(timeline, ms);
  // Between turns the last speaker keeps the chip (no flicker in the short pauses).
  const current = seg ?? speakingAt(timeline, ms);
  const debaters = timeline.speakers.filter((s) => s.role === 'debater');
  const speaker = current ? timeline.speakers.find((s) => s.id === current.speaker_id) : undefined;
  const active = seg ? speaker : undefined;
  const inIntro = ms < 0;
  const inOutro = ms >= timeline.total_ms;
  const half = Math.ceil(debaters.length / 2);

  const verdictSeg = timeline.segments.find((s) => s.turn_type === 'verdict');
  const verdictAt = timeline.verdict?.winner_id ? (verdictSeg ? verdictSeg.end_ms - VERDICT_LEAD_MS : timeline.total_ms) : Infinity;
  const showVerdict = ms >= verdictAt;
  // A battle moves on its beat (lights, logos, the camera's bounce); a debate's logo on the voice.
  const groove = timelineFormat(timeline).id === 'rap_battle' ? grooveAt(timeline, current, ms) : null;
  const pulse = groove ? groove.pulse * (groove.strong ? 1 : 0.5) : 0.6 * levelAt(seg, ms);
  const card = inIntro || inOutro ? null : roundCardAt(timeline, ms);
  const cam = cameraAt(ms, groove, card);
  const flash = flashAt(card, ms);
  const lights = groove && debaters.length >= 2 ? { colors: [debaters[0].color, debaters[1].color] as [string, string], active: speaker?.role === 'debater' ? speaker.color : null, groove } : null;

  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <Background accent={glowColorAt(timeline, ms, HOST_COLOR)} ms={ms} lights={lights} />
      <Sequence from={msToFrame(INTRO_MS)} durationInFrames={msToFrame(timeline.total_ms) + 2} premountFor={fps}>
        <Audio src={`${mediaBase}/${timeline.full_audio_wav}`} />
      </Sequence>

      {inIntro && <IntroCard timeline={timeline} />}

      {!inIntro && !inOutro && (
        <div style={{ position: 'absolute', inset: 0, opacity: showVerdict ? 0.05 : 1, transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.scale})` }}>
          <div style={{ position: 'absolute', top: 2.2 * U, left: 2.4 * U, right: 2.4 * U, height: barHeight(U), display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <BrandMark u={U} />
            <div>{current && <RoundChip roundId={current.round_id} label={current.round_label} u={U} />}</div>
          </div>
          {speaker && (
            <div style={{ position: 'absolute', top: 2.2 * U, left: 0, right: 0, height: barHeight(U), display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <SpeakingChip speaker={speaker} seg={seg} offsetMs={INTRO_MS} u={U} />
            </div>
          )}

          <SideColumn speakers={debaters.slice(0, half)} debaters={debaters} x={SIDE_X} activeId={active?.id} pulse={pulse} />
          <SideColumn speakers={debaters.slice(half)} debaters={debaters} x={LONG_W - SIDE_X - SIDE_W} activeId={active?.id} pulse={pulse} />

          <SceneStage timeline={timeline} mediaBase={mediaBase} seg={current} ms={ms} x={STAGE.x} y={STAGE.y} w={STAGE.w} h={STAGE.h} k={1} card={card} pulse={groove ? pulse : 0} />

          {/* A rap verse's lines are on the stage (VerseStage): no captions under them. */}
          {!showVerdict && seg?.turn_type !== 'verse' && (
            <div style={{ position: 'absolute', left: 4 * U, right: 4 * U, bottom: 3 * U, display: 'flex', justifyContent: 'center' }}>
              <Captions seg={seg} offsetMs={INTRO_MS} fontSize={2.4 * U} maxWidth={LONG_W - 8 * U} />
            </div>
          )}
        </div>
      )}

      {flash > 0 && <AbsoluteFill style={{ background: '#FFFFFF', opacity: flash }} />}
      {showVerdict && <VerdictCard timeline={timeline} big sinceMs={ms - verdictAt} />}
      {inOutro && !timeline.verdict?.winner_id && <EndCard big text="Thanks for watching" sinceMs={ms - timeline.total_ms} />}
    </AbsoluteFill>
  );
};
