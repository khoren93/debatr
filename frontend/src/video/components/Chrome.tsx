import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Timeline } from '../../api/timeline';
import { APP_NAME } from '../../lib/brand';
import { timelineFormat } from '../../lib/formats';
import { ACCENT, DISPLAY_FONT, FONT, INTRO_MS, MONO_FONT, barHeight, headlineSize } from '../constants';
import { roundLabel } from '../utils';
import { FaceOff } from './FaceOff';
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

/** Mono pill in the top bar, as tall as the speaking chip. */
export const LabelChip = ({ label, u, color = HOST }: { label: string; u: number; color?: string }) => (
  <div style={{ display: 'flex', alignItems: 'center', height: barHeight(u), boxSizing: 'border-box', padding: `0 ${1.5 * u}px`, borderRadius: 999, background: 'rgba(10,11,15,0.7)', border: '2px solid #ffffff24', fontFamily: MONO_FONT, fontSize: 1.25 * u, letterSpacing: 0.1 * 1.25 * u, color, whiteSpace: 'nowrap' }}>
    {label}
  </div>
);

/** "ROUND 1" / "VERDICT" pill in the top-right corner. */
export const RoundChip = ({ roundId, label, u }: { roundId: string; label?: string | null; u: number }) => <LabelChip label={roundLabel(roundId, label).toUpperCase()} u={u} />;

/** The long video's opening: the face-off under the brand bar, the question below. Fully drawn
 *  on frame 0 (the player's poster, the MP4's first frame); it fades into the studio at the end.
 *  The middle of the frame stays empty for the player's play button. */
export const IntroCard = ({ timeline }: { timeline: Timeline }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;
  const length = INTRO_MS / 1000;
  const o = interpolate(t, [length - 0.4, length], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const u = width / 100;
  const debaters = timeline.speakers.filter((s) => s.role === 'debater');
  const size = headlineSize(timeline.topic, 4 * u);
  return (
    <div style={{ position: 'absolute', inset: 0, opacity: o, fontFamily: FONT }}>
      <FaceOff debaters={debaters} width={width} height={height} logoY={0.31} logoSize={13 * u} t={t} length={length} />
      <div style={{ position: 'absolute', top: 2.2 * u, left: 2.4 * u, right: 2.4 * u, height: barHeight(u), display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <BrandMark u={u} />
        <LabelChip label={timelineFormat(timeline).label} u={u} color={ACCENT} />
      </div>
      <div style={{ position: 'absolute', left: 7 * u, right: 7 * u, bottom: 5 * u, textAlign: 'center', fontFamily: DISPLAY_FONT, fontSize: size, fontWeight: 800, letterSpacing: -0.03 * size, lineHeight: 1.06, color: '#F2F3F7' }}>{timeline.topic}</div>
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
      <div style={{ fontSize: big ? 36 : 30, color: '#ffffffb3', fontWeight: 600 }}>{winner ? `wins this ${timelineFormat(timeline).show}` : 'no winner'}</div>
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
