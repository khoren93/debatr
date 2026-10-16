import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline } from '../../api/timeline';
import { ACCENT, FONT } from '../constants';
import { roundLabel } from '../utils';

/** One-line topic in a corner once the intro has shown it in big (context for viewers who skip). */
export const TopicChip = ({ topic, sinceMs, maxChars, fontSize }: { topic: string; sinceMs: number; maxChars: number; fontSize: number }) => {
  const o = interpolate(sinceMs, [0, 500], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const text = topic.length > maxChars ? `${topic.slice(0, maxChars - 1).trimEnd()}…` : topic;
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: fontSize * 0.55, padding: `${fontSize * 0.45}px ${fontSize * 0.9}px`, borderRadius: 999, background: '#0f172acc', border: '2px solid #ffffff1f', fontFamily: FONT, opacity: o }}>
      <span style={{ fontSize: fontSize * 0.75, letterSpacing: 4, color: ACCENT, fontWeight: 800 }}>DEBATR</span>
      <span style={{ fontSize, fontWeight: 700, color: '#ffffffd9', whiteSpace: 'nowrap' }}>{text}</span>
    </div>
  );
};

export const RoundChip =({ roundId, fontSize }: { roundId: string; fontSize: number }) => (
  <div style={{ fontFamily: FONT, display: 'inline-block', padding: `${fontSize * 0.35}px ${fontSize * 0.9}px`, borderRadius: 999, background: roundId === 'verdict' ? '#FFC46B' : '#ffffff1a', border: '2px solid #ffffff33', color: roundId === 'verdict' ? '#3a2600' : '#fff', fontWeight: 800, fontSize, letterSpacing: 2, textTransform: 'uppercase' }}>
    {roundLabel(roundId)}
  </div>
);

export const IntroCard = ({ timeline, big }: { timeline: Timeline; big: boolean }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const o = interpolate(t, [0, 0.35, 1.4, 1.8], [0, 1, 1, 0], { extrapolateRight: 'clamp' });
  const y = interpolate(t, [0, 0.5], [30, 0], { extrapolateRight: 'clamp' });
  const debaters = timeline.speakers.filter((s) => s.role === 'debater');
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: big ? 40 : 28, opacity: o, transform: `translateY(${y}px)`, fontFamily: FONT, padding: 60, textAlign: 'center' }}>
      <div style={{ fontSize: big ? 34 : 26, letterSpacing: 8, color: ACCENT, fontWeight: 800 }}>DEBATR</div>
      <div style={{ fontSize: big ? 84 : 64, fontWeight: 900, color: '#fff', lineHeight: 1.05, maxWidth: big ? 1500 : 900 }}>{timeline.topic}</div>
      <div style={{ fontSize: big ? 44 : 36, fontWeight: 700, color: '#ffffffcc' }}>
        {debaters.map((d, i) => (
          <span key={d.id}>
            {i > 0 && <span style={{ opacity: 0.6 }}> vs </span>}
            <span style={{ color: d.color }}>{d.name}</span>
          </span>
        ))}
      </div>
    </div>
  );
};

export const VerdictCard = ({ timeline, big, sinceMs }: { timeline: Timeline; big: boolean; sinceMs: number }) => {
  const t = Math.max(0, sinceMs) / 1000;
  const s = interpolate(t, [0, 0.4], [0.8, 1], { extrapolateRight: 'clamp' });
  const o = interpolate(t, [0, 0.3], [0, 1], { extrapolateRight: 'clamp' });
  const winner = timeline.speakers.find((sp) => sp.id === timeline.verdict?.winner_id);
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 20, opacity: o, transform: `scale(${s})`, fontFamily: FONT, textAlign: 'center', padding: 60 }}>
      <div style={{ fontSize: big ? 40 : 30, letterSpacing: 10, color: '#FFC46B', fontWeight: 900 }}>VERDICT</div>
      <div style={{ fontSize: big ? 110 : 84, fontWeight: 900, color: winner?.color ?? '#fff', lineHeight: 1, textShadow: `0 0 60px ${winner?.color ?? '#fff'}66` }}>{winner?.name ?? '—'}</div>
      <div style={{ fontSize: big ? 36 : 30, color: '#ffffffb3', fontWeight: 600 }}>{winner ? 'wins this debate' : 'no winner'}</div>
    </div>
  );
};

export const EndCard = ({ big, text, sinceMs }: { big: boolean; text: string; sinceMs: number }) => {
  const o = interpolate(Math.max(0, sinceMs) / 1000, [0, 0.4], [0, 1], { extrapolateRight: 'clamp' });
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, opacity: o, fontFamily: FONT, textAlign: 'center', padding: 60 }}>
      <div style={{ fontSize: big ? 30 : 24, letterSpacing: 8, color: ACCENT, fontWeight: 800 }}>DEBATR</div>
      <div style={{ fontSize: big ? 64 : 52, fontWeight: 900, color: '#fff', maxWidth: 1200 }}>{text}</div>
    </div>
  );
};
