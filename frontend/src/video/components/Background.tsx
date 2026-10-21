import { AbsoluteFill, useVideoConfig } from 'remotion';
import { ACCENT } from '../constants';
import { withAlpha, type Groove } from '../groove';

/** One soft glow: an ellipse with radii `rx` × `ry` around (`cx`, `cy`), turned `rotate` degrees
 *  around that centre. The web renderer only draws centred, unsized radial gradients, so each
 *  glow is its own box (farthest-corner = r). */
const Glow = ({ cx, cy, rx, ry, color, rotate = 0 }: { cx: number; cy: number; rx: number; ry: number; color: string; rotate?: number }) => {
  const w = rx * Math.SQRT2;
  const h = ry * Math.SQRT2;
  return <div style={{ position: 'absolute', left: cx - w / 2, top: cy - h / 2, width: w, height: h, background: `radial-gradient(${color} 0%, transparent 60%)`, transform: rotate ? `rotate(${rotate}deg)` : undefined }} />;
};

const TAU = Math.PI * 2;
const wave = (ms: number, period: number, phase = 0) => Math.sin((TAU * ms) / period + phase);

/** A battle's club lights: the rappers' colours (`colors[0]`, `colors[1]`), the active one's
 *  beams brighter. */
export interface Lights {
  colors: [string, string];
  active: string | null;
  groove: Groove;
}

/** Beams from the top edge: a rapper's colour on the outside (`rapper` 0 / 1), the accent inside. */
const BEAMS: { x: number; rapper: 0 | 1 | null; lean: number }[] = [
  { x: 0.13, rapper: 0, lean: 11 },
  { x: 0.37, rapper: null, lean: 5 },
  { x: 0.63, rapper: null, lean: -5 },
  { x: 0.87, rapper: 1, lean: -11 },
];

/** Four light beams swinging over two bars in opposite pairs and flaring on every beat (more on
 *  the kick), and a floor glow in the active colour breathing with them. */
const StageLights = ({ colors, active, groove, width, height }: Lights & { width: number; height: number }) => {
  const flare = groove.pulse * (groove.strong ? 1 : 0.55);
  return (
    <>
      {BEAMS.map((beam, i) => {
        const color = beam.rapper === null ? ACCENT : colors[beam.rapper];
        const lit = beam.rapper !== null && color === active ? 1.45 : 1;
        const swing = beam.lean + 13 * Math.sin((TAU * groove.phase) / 8 + (i % 2 ? Math.PI : 0));
        const alpha = (beam.rapper === null ? 0.07 : 0.13) * lit + 0.2 * flare * lit;
        return <Glow key={i} cx={width * beam.x} cy={-height * 0.04} rx={width * 0.075} ry={height * 1.1} color={withAlpha(color, alpha)} rotate={swing} />;
      })}
      <Glow cx={width * 0.5} cy={height * 1.04} rx={width * 0.6} ry={height * 0.28} color={withAlpha(active ?? ACCENT, 0.09 + 0.16 * flare)} />
    </>
  );
};

/** Studio backdrop: deep navy, a glow in the speaker's colour top-left and a warm one
 *  bottom-right, both drifting slowly (`ms`: the track's clock); a battle adds its club lights. */
export const Background = ({ accent, ms, lights }: { accent: string; ms: number; lights?: Lights | null }) => {
  const { width, height } = useVideoConfig();
  const lift = lights ? 0.04 * lights.groove.pulse * (lights.groove.strong ? 1 : 0.5) : 0;
  return (
    <AbsoluteFill style={{ background: 'linear-gradient(180deg, #0E1424, #0A0D18)' }}>
      <Glow cx={width * (0.25 + 0.06 * wave(ms, 23_000))} cy={height * (0.15 + 0.07 * wave(ms, 31_000, 1))} rx={width * 0.6} ry={height * 0.5} color={withAlpha(accent, 0.12 + lift)} />
      <Glow cx={width * (0.85 + 0.05 * wave(ms, 27_000, 2))} cy={height * (0.9 + 0.06 * wave(ms, 19_000, 3))} rx={width * 0.5} ry={height * 0.6} color={withAlpha('#FF7A66', 0.1)} />
      {lights && <StageLights {...lights} width={width} height={height} />}
    </AbsoluteFill>
  );
};
