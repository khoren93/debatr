import { useId } from 'react';
import { Easing, interpolate } from 'remotion';
import type { TimelineSpeaker } from '../../api/timeline';
import { ACCENT, DISPLAY_FONT, MONO_FONT } from '../constants';
import { speakerModelId } from '../speakers';
import { ModelLogo } from './ModelLogo';

/** Horizontal lean of every seam between two sides, as a share of the width (top vs bottom). */
const LEAN = 0.05;
const INK = '#0A0B0F';

interface FaceOffProps {
  debaters: TimelineSpeaker[];
  width: number;
  height: number;
  /** Height of the logo centres, as a share of the height. */
  logoY: number;
  /** Logo size in px with two sides (three or four get smaller ones). */
  logoSize: number;
  /** Seconds since the card appeared and its length: the sides close in over it. */
  t: number;
  length: number;
}

const seamX = (k: number, n: number, w: number, y: number, h: number) => (k / n) * w + LEAN * w * (1 - (2 * y) / h);

/**
 * The debaters face off, as on the gallery cover: each on a slanted side in its speaker colour,
 * its provider logo big and glowing, a VS mark on every seam. Frame 0 is the full picture (it is
 * the player's poster and the first frame of the MP4); over `length` the logos close in and the
 * VS mark pulses. Everything that is not a raster logo is one <svg>, which the web renderer
 * draws as an image (gradients, pattern and polygons included).
 */
export const FaceOff = ({ debaters, width: w, height: h, logoY, logoSize, t, length }: FaceOffProps) => {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const sides = debaters.slice(0, 4);
  const n = Math.max(sides.length, 1);
  const size = n <= 2 ? logoSize : n === 3 ? logoSize * 0.72 : logoSize * 0.56;
  const cy = h * logoY;
  const push = interpolate(t, [0, length], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) });
  const vsPulse = interpolate(t, [0.12, 0.32, 0.62], [1, 1.16, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const vs = n <= 2 ? size * 0.46 : size * 0.52;
  const nameSize = n <= 2 ? size * 0.13 : size * 0.15;

  const poly = (i: number) => {
    const xt = (k: number) => (k === 0 ? 0 : k === n ? w : (k / n) * w + LEAN * w);
    const xb = (k: number) => (k === 0 ? 0 : k === n ? w : (k / n) * w - LEAN * w);
    return `${xt(i)},0 ${xt(i + 1)},0 ${xb(i + 1)},${h} ${xb(i)},${h}`;
  };

  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ position: 'absolute', inset: 0, transform: `scale(${1 + 0.025 * push})` }}>
        <defs>
          {sides.map((d, i) => {
            const cx = ((i + 0.5) / n) * w;
            return (
              <g key={d.id}>
                <radialGradient id={`${uid}g${i}`} gradientUnits="userSpaceOnUse" cx={cx} cy={cy} r={Math.max(w / n, h) * 0.75}>
                  <stop offset="0" stopColor={d.color} stopOpacity={0.42} />
                  <stop offset="0.4" stopColor={d.color} stopOpacity={0.13} />
                  <stop offset="1" stopColor={d.color} stopOpacity={0} />
                </radialGradient>
                <linearGradient id={`${uid}l${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor={d.color} stopOpacity={0.16} />
                  <stop offset="1" stopColor={d.color} stopOpacity={0.05} />
                </linearGradient>
              </g>
            );
          })}
          <pattern id={`${uid}h`} width={w / 110} height={w / 110} patternUnits="userSpaceOnUse" patternTransform="rotate(10)">
            <line x1="0" y1="0" x2="0" y2={w / 110} stroke="#FFFFFF" strokeOpacity={0.035} strokeWidth={w / 1100} />
          </pattern>
          <linearGradient id={`${uid}b`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0.45" stopColor={INK} stopOpacity={0} />
            <stop offset="1" stopColor={INK} stopOpacity={0.88} />
          </linearGradient>
        </defs>
        <rect width={w} height={h} fill={INK} />
        {sides.map((d, i) => (
          <g key={d.id}>
            <polygon points={poly(i)} fill={`url(#${uid}l${i})`} />
            <polygon points={poly(i)} fill={`url(#${uid}g${i})`} />
          </g>
        ))}
        <rect width={w} height={h} fill={`url(#${uid}h)`} />
        {sides.slice(1).map((d, k) => (
          <line key={d.id} x1={((k + 1) / n) * w + LEAN * w} y1={0} x2={((k + 1) / n) * w - LEAN * w} y2={h} stroke="#FFFFFF" strokeOpacity={0.55} strokeWidth={Math.max(2, w / 640)} />
        ))}
        <rect width={w} height={h} fill={`url(#${uid}b)`} />
      </svg>

      {sides.map((d, i) => {
        const cx = ((i + 0.5) / n) * w;
        // Every side leans toward the middle of the frame.
        const dx = Math.sign(w / 2 - cx) * w * 0.012 * push;
        return (
          <div key={d.id} style={{ position: 'absolute', left: cx - w / n / 2 + dx, top: cy - size / 2, width: w / n, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{ position: 'relative', width: size, height: size, transform: `scale(${1 + 0.06 * push})` }}>
              <div style={{ position: 'absolute', left: -size * 0.6, top: -size * 0.6, width: size * 2.2, height: size * 2.2, background: `radial-gradient(${d.color}55 0%, transparent 55%)` }} />
              <div style={{ position: 'relative' }}>
                <ModelLogo modelId={speakerModelId(d)} size={size} />
              </div>
            </div>
            <div style={{ marginTop: size * 0.2, maxWidth: (w / n) * 0.86, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: MONO_FONT, fontWeight: 500, fontSize: nameSize, letterSpacing: n <= 2 ? nameSize * 0.14 : nameSize * 0.04, color: d.color, textTransform: 'uppercase' }}>{d.name}</div>
          </div>
        );
      })}

      {sides.slice(1).map((d, k) => (
        <div key={d.id} style={{ position: 'absolute', left: seamX(k + 1, n, w, cy, h) - vs / 2, top: cy - vs / 2, width: vs, height: vs }}>
          <div style={{ position: 'absolute', left: -vs * 0.5, top: -vs * 0.5, width: vs * 2, height: vs * 2, background: `radial-gradient(${ACCENT}40 0%, transparent 55%)` }} />
          <div
            style={{
              position: 'absolute',
              inset: 0,
              borderRadius: vs / 2,
              background: INK,
              border: `${Math.max(3, vs * 0.04)}px solid ${ACCENT}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transform: `rotate(-8deg) scale(${vsPulse})`,
              fontFamily: DISPLAY_FONT,
              fontWeight: 800,
              fontSize: vs * 0.4,
              color: ACCENT,
              lineHeight: 1,
            }}
          >
            VS
          </div>
        </div>
      ))}
    </div>
  );
};
