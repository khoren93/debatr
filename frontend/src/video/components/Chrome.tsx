import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline } from '../../api/timeline';
import { APP_NAME } from '../../lib/brand';
import { ACCENT, DISPLAY_FONT, FONT, MONO_FONT, barHeight } from '../constants';
import { roundLabel } from '../utils';
import { LogoTile } from './ModelLogo';

const HOST = '#FFC46B';
const INK = '#0A0B0F';

/** The mark of public/favicon.svg. Colours are attributes: the MP4 renderer draws <svg> as an image. */
export const BrandLogo = ({ size }: { size: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" style={{ display: 'block', flexShrink: 0 }}>
    <rect width="64" height="64" rx="18" fill={ACCENT} />
    <path d="M14 18a6 6 0 0 1 6-6h11a19 19 0 0 1 0 38h-7l-10 8.5V18Z" fill={INK} />
    <g fill={ACCENT}>
      <rect x="20.9" y="26" width="5" height="10" rx="2.5" />
      <rect x="28.5" y="21" width="5" height="20" rx="2.5" />
      <rect x="36.1" y="24.5" width="5" height="13" rx="2.5" />
    </g>
  </svg>
);

/** Mark + wordmark, `size` px tall. */
export const BrandLockup = ({ size }: { size: number }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: size * 0.3, height: size }}>
    <BrandLogo size={size} />
    <span style={{ fontFamily: DISPLAY_FONT, fontWeight: 700, fontSize: size * 0.5, letterSpacing: -0.025 * size * 0.5, lineHeight: 1, color: '#F2F3F7', whiteSpace: 'nowrap' }}>{APP_NAME}</span>
  </div>
);

/** The brand in the top-left corner, as tall as the speaking chip. */
export const BrandMark = ({ u }: { u: number }) => <BrandLockup size={barHeight(u)} />;

/** "ROUND 1" / "VERDICT" pill in the top-right corner, as tall as the speaking chip. */
export const RoundChip = ({ roundId, u }: { roundId: string; u: number }) => (
  <div style={{ display: 'flex', alignItems: 'center', height: barHeight(u), boxSizing: 'border-box', padding: `0 ${1.5 * u}px`, borderRadius: 999, background: 'rgba(10,11,15,0.7)', border: '2px solid #ffffff24', fontFamily: MONO_FONT, fontSize: 1.25 * u, letterSpacing: 0.1 * 1.25 * u, color: HOST, whiteSpace: 'nowrap' }}>
    {roundLabel(roundId).toUpperCase()}
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
      <BrandLockup size={big ? 72 : 60} />
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
      <BrandLockup size={big ? 64 : 56} />
      <div style={{ fontFamily: DISPLAY_FONT, fontSize: big ? 64 : 52, fontWeight: 800, color: '#F2F3F7', maxWidth: 1200 }}>{text}</div>
    </div>
  );
};
