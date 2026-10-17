import { AbsoluteFill, useVideoConfig } from 'remotion';

/** One soft glow: an ellipse with radii `rx` × `ry` around (`cx`, `cy`). The web renderer only
 *  draws centred, unsized radial gradients, so each glow is its own box (farthest-corner = r). */
const Glow = ({ cx, cy, rx, ry, color }: { cx: number; cy: number; rx: number; ry: number; color: string }) => {
  const w = rx * Math.SQRT2;
  const h = ry * Math.SQRT2;
  return <div style={{ position: 'absolute', left: cx - w / 2, top: cy - h / 2, width: w, height: h, background: `radial-gradient(${color} 0%, transparent 60%)` }} />;
};

/** Studio backdrop: deep navy with a glow in the speaker's colour top-left and a warm one bottom-right. */
export const Background = ({ accent }: { accent: string }) => {
  const { width, height } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: 'linear-gradient(180deg, #0E1424, #0A0D18)' }}>
      <Glow cx={width * 0.25} cy={height * 0.15} rx={width * 0.6} ry={height * 0.5} color={`${accent}1f`} />
      <Glow cx={width * 0.85} cy={height * 0.9} rx={width * 0.5} ry={height * 0.6} color="#FF7A661a" />
    </AbsoluteFill>
  );
};
