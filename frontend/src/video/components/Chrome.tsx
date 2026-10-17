import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline } from '../../api/timeline';
import { ACCENT, BRAND, DISPLAY_FONT, FONT, MONO_FONT } from '../constants';
import { roundLabel } from '../utils';
import { LogoTile } from './ModelLogo';

const HOST = '#FFC46B';

/** "ROUND 1" / "VERDICT" pill in the top-left corner. */
export const RoundChip = ({ roundId, u }: { roundId: string; u: number }) => (
  <div style={{ display: 'inline-block', padding: `${0.6 * u}px ${1.2 * u}px`, borderRadius: 999, border: '2px solid #ffffff24', fontFamily: MONO_FONT, fontSize: 1.05 * u, letterSpacing: 0.1 * 1.05 * u, color: HOST, whiteSpace: 'nowrap' }}>
    {roundLabel(roundId).toUpperCase()}
  </div>
);

/** The brand in the top-right corner. */
export const BrandMark = ({ u }: { u: number }) => <div style={{ fontFamily: MONO_FONT, fontSize: 1.05 * u, letterSpacing: 0.1 * 1.05 * u, color: ACCENT, whiteSpace: 'nowrap' }}>{BRAND}</div>;

export const IntroCard = ({ timeline, big }: { timeline: Timeline; big: boolean }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const o = interpolate(t, [0, 0.35, 1.4, 1.8], [0, 1, 1, 0], { extrapolateRight: 'clamp' });
  const y = interpolate(t, [0, 0.5], [30, 0], { extrapolateRight: 'clamp' });
  const debaters = timeline.speakers.filter((s) => s.role === 'debater');
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: big ? 40 : 28, opacity: o, transform: `translateY(${y}px)`, fontFamily: FONT, padding: 60, textAlign: 'center' }}>
      <div style={{ fontFamily: MONO_FONT, fontSize: big ? 30 : 26, letterSpacing: 8, color: ACCENT }}>{BRAND}</div>
      <div style={{ fontFamily: DISPLAY_FONT, fontSize: big ? 84 : 64, fontWeight: 800, letterSpacing: big ? -2.5 : -2, color: '#F2F3F7', lineHeight: 1.05, maxWidth: big ? 1500 : 900 }}>{timeline.topic}</div>
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
      <div style={{ fontFamily: MONO_FONT, fontSize: big ? 36 : 28, letterSpacing: 10, color: HOST }}>VERDICT</div>
      {winner && <LogoTile speaker={winner} size={big ? 150 : 120} framed />}
      <div style={{ fontFamily: DISPLAY_FONT, fontSize: big ? 110 : 84, fontWeight: 800, letterSpacing: -3, color: winner?.color ?? '#fff', lineHeight: 1, textShadow: `0 0 60px ${winner?.color ?? '#fff'}66` }}>{winner?.name ?? '—'}</div>
      <div style={{ fontSize: big ? 36 : 30, color: '#ffffffb3', fontWeight: 600 }}>{winner ? 'wins this debate' : 'no winner'}</div>
    </div>
  );
};

export const EndCard = ({ big, text, sinceMs }: { big: boolean; text: string; sinceMs: number }) => {
  const o = interpolate(Math.max(0, sinceMs) / 1000, [0, 0.4], [0, 1], { extrapolateRight: 'clamp' });
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, opacity: o, fontFamily: FONT, textAlign: 'center', padding: 60 }}>
      <div style={{ fontFamily: MONO_FONT, fontSize: big ? 28 : 24, letterSpacing: 8, color: ACCENT }}>{BRAND}</div>
      <div style={{ fontFamily: DISPLAY_FONT, fontSize: big ? 64 : 52, fontWeight: 800, color: '#F2F3F7', maxWidth: 1200 }}>{text}</div>
    </div>
  );
};
