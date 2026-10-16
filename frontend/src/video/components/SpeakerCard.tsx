import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { TimelineSegment, TimelineSpeaker } from '../../api/timeline';
import { FONT } from '../constants';
import { Mascot } from '../Mascot';
import { frameToMs, levelAt } from '../utils';
import { Waveform } from './Waveform';

export const SpeakerCard = ({ speaker, seg, offsetMs, active, width, compact = false }: { speaker: TimelineSpeaker; seg: TimelineSegment | null; offsetMs: number; active: boolean; width: number; compact?: boolean }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = frameToMs(frame, fps) - offsetMs;
  const level = active ? levelAt(seg, ms) : 0;
  const scale = interpolate(level, [0, 1], [1, 1.035]);
  const size = compact ? width * 0.42 : width * 0.5;
  // Narrow columns (4 debaters, Shorts) scale the type down with the card.
  const nameSize = compact ? Math.min(34, width * 0.12) : 44;
  const modelSize = compact ? Math.min(20, width * 0.07) : 24;
  return (
    <div
      style={{
        width,
        padding: compact ? 18 : 26,
        borderRadius: 28,
        background: active ? `linear-gradient(180deg, ${speaker.color}22, #0f172a)` : '#0f172acc',
        border: `3px solid ${active ? speaker.color : '#27314f'}`,
        boxShadow: active ? `0 0 ${40 + level * 60}px ${speaker.color}66` : 'none',
        opacity: active ? 1 : 0.55,
        transform: `scale(${active ? scale : 0.96})`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 12,
        fontFamily: FONT,
      }}
    >
      <Mascot kind={speaker.mascot} color={speaker.color} size={size} mouth={active ? level : 0} talking={active} />
      <div style={{ fontSize: nameSize, fontWeight: 800, color: '#fff', letterSpacing: -0.5, textAlign: 'center', lineHeight: 1.05 }}>{speaker.name}</div>
      <div style={{ fontSize: modelSize, fontWeight: 600, color: speaker.color, textTransform: 'uppercase', letterSpacing: 2, textAlign: 'center' }}>{speaker.model}</div>
      <Waveform seg={active ? seg : null} offsetMs={offsetMs} color={speaker.color} width={width * 0.7} height={compact ? 40 : 56} />
    </div>
  );
};

/** Horizontal pill for the host (moderator, or the judge during the verdict) at the top. */
export const HostChip = ({ speaker, seg, offsetMs, active, width }: { speaker: TimelineSpeaker; seg: TimelineSegment | null; offsetMs: number; active: boolean; width: number }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const ms = frameToMs(frame, fps) - offsetMs;
  const level = active ? levelAt(seg, ms) : 0;
  return (
    <div
      style={{
        width,
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '8px 22px 8px 10px',
        borderRadius: 999,
        background: active ? `linear-gradient(90deg, ${speaker.color}2e, #0f172a)` : '#0f172acc',
        border: `3px solid ${active ? speaker.color : '#27314f'}`,
        boxShadow: active ? `0 0 ${30 + level * 50}px ${speaker.color}55` : 'none',
        opacity: active ? 1 : 0.6,
        fontFamily: FONT,
      }}
    >
      <Mascot kind={speaker.mascot} color={speaker.color} size={72} mouth={level} talking={active} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 28, fontWeight: 800, color: '#fff', lineHeight: 1.05, whiteSpace: 'nowrap', overflow: 'hidden' }}>{speaker.name}</div>
        <div style={{ fontSize: 15, fontWeight: 700, color: speaker.color, textTransform: 'uppercase', letterSpacing: 2, marginTop: 4, whiteSpace: 'nowrap', overflow: 'hidden' }}>{speaker.model}</div>
      </div>
      <Waveform seg={active ? seg : null} offsetMs={offsetMs} color={speaker.color} width={96} height={36} bars={12} />
    </div>
  );
};
