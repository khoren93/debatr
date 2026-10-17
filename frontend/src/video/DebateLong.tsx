import { Audio } from '@remotion/media';
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline, TimelineSegment, TimelineSpeaker } from '../api/timeline';
import { Background } from './components/Background';
import { Captions } from './components/Captions';
import { EndCard, IntroCard, RoundChip, TopicChip, VerdictCard } from './components/Chrome';
import { HostChip, SpeakerCard } from './components/SpeakerCard';
import { ACCENT, INTRO_MS, LONG_W } from './constants';
import { frameToMs, msToFrame, segmentAt } from './utils';
import { SceneStage } from './visuals/SceneStage';

export interface DebateProps {
  timeline: Timeline;
  mediaBase: string; // absolute URL of the debate's media folder
  [key: string]: unknown;
}

const VERDICT_LEAD_MS = 2200;
// Studio layout: host on top, debaters in side columns, the visual stage in the middle,
// captions at the bottom.
const STAGE = { x: 380, y: 150, w: 1160, h: 700 };
const SIDE_W = 280;
const SIDE_X = 50;

const SideColumn = ({ speakers, x, seg, activeId }: { speakers: TimelineSpeaker[]; x: number; seg: TimelineSegment | null; activeId: string | undefined }) => (
  <div style={{ position: 'absolute', left: x, top: STAGE.y, width: SIDE_W, height: STAGE.h, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 28 }}>
    {speakers.map((d) => (
      <SpeakerCard key={d.id} speaker={d} seg={seg} offsetMs={INTRO_MS} active={activeId === d.id} width={SIDE_W} compact />
    ))}
  </div>
);

export const DebateLong = ({ timeline, mediaBase }: DebateProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = frameToMs(frame, fps) - INTRO_MS;
  const seg = segmentAt(timeline, ms);
  const debaters = timeline.speakers.filter((s) => s.role === 'debater');
  const moderator = timeline.speakers.find((s) => s.role === 'moderator');
  const judge = timeline.speakers.find((s) => s.role === 'judge');
  const active = seg ? timeline.speakers.find((s) => s.id === seg.speaker_id) : null;
  const hostActive = active?.role === 'moderator' || active?.role === 'judge';
  const host = active?.role === 'judge' && judge ? judge : (moderator ?? judge);
  const inIntro = ms < 0;
  const inOutro = ms >= timeline.total_ms;
  const accent = active?.color ?? ACCENT;
  const half = Math.ceil(debaters.length / 2);

  const verdictSeg = timeline.segments.find((s) => s.turn_type === 'verdict');
  const verdictAt = timeline.verdict?.winner_id ? (verdictSeg ? verdictSeg.end_ms - VERDICT_LEAD_MS : timeline.total_ms) : Infinity;
  const showVerdict = ms >= verdictAt;

  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <Background accent={accent} />
      <Sequence from={msToFrame(INTRO_MS)} durationInFrames={msToFrame(timeline.total_ms) + 2} premountFor={fps}>
        <Audio src={`${mediaBase}/${timeline.full_audio_wav}`} />
      </Sequence>

      {inIntro && <IntroCard timeline={timeline} big />}

      {!inIntro && !inOutro && (
        <div style={{ position: 'absolute', inset: 0, opacity: showVerdict ? 0.05 : 1 }}>
          <div style={{ position: 'absolute', top: 40, left: SIDE_X }}>
            <TopicChip topic={timeline.topic} sinceMs={ms} maxChars={42} fontSize={22} />
          </div>
          <div style={{ position: 'absolute', top: 42, right: SIDE_X }}>{seg && <RoundChip roundId={seg.round_id} fontSize={20} />}</div>
          {host && (
            <div style={{ position: 'absolute', top: 24, left: (LONG_W - 420) / 2 }}>
              <HostChip speaker={host} seg={seg} offsetMs={INTRO_MS} active={hostActive} width={420} />
            </div>
          )}

          <SideColumn speakers={debaters.slice(0, half)} x={SIDE_X} seg={seg} activeId={active?.id} />
          <SideColumn speakers={debaters.slice(half)} x={LONG_W - SIDE_X - SIDE_W} seg={seg} activeId={active?.id} />

          <SceneStage timeline={timeline} mediaBase={mediaBase} seg={seg} ms={ms} x={STAGE.x} y={STAGE.y} w={STAGE.w} h={STAGE.h} k={1} />

          {!showVerdict && (
            <div style={{ position: 'absolute', left: 0, right: 0, bottom: 56 }}>
              <Captions seg={seg} offsetMs={INTRO_MS} color={accent} fontSize={52} maxWidth={1500} />
            </div>
          )}
        </div>
      )}

      {showVerdict && <VerdictCard timeline={timeline} big sinceMs={ms - verdictAt} />}
      {inOutro && !timeline.verdict?.winner_id && <EndCard big text="Thanks for watching" sinceMs={ms - timeline.total_ms} />}
    </AbsoluteFill>
  );
};
