import type { FlowScene, IconsScene, TimelineScene } from '../../api/visuals';
import { DISPLAY_FONT, FONT } from '../constants';
import { INK, INK_DIM, easeInOut, easeOut, onEllipse, ramp, seedOf, sketch, type Pt } from './draw';
import { DrawnIcon, InkLayer, Reveal, Stroke } from './Ink';
import type { SceneCtx } from './scene';

const latest = (items: number[], t: number) => items.reduce((cur, at, i) => (t >= at ? i : cur), 0);

/** Cause → effect chain or a cycle: circled pictograms joined by arrows, step by step. */
export const FlowView = ({ scene, ctx }: { scene: FlowScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, id } = ctx;
  const seed = seedOf(id);
  const n = scene.steps.length;
  const cycle = scene.layout === 'cycle' && n >= 3;
  const cx = w / 2;
  const cy = h * 0.43;
  const rx = w * (w / h < 1.5 ? 0.3 : 0.26);
  const ry = h * 0.3;
  const slot = w / n;
  const D = cycle ? Math.min(150 * k, ((2 * Math.PI * Math.min(rx, ry)) / n) * 0.5) : Math.min(slot * 0.6, h * 0.4, 190 * k);
  const centers: Pt[] = scene.steps.map((_, i) => (cycle ? onEllipse(cx, cy, rx, ry, (2 * Math.PI * i) / n) : [slot * (i + 0.5), h * 0.38]));
  const at = (i: number) => items[i] ?? i * 900;
  const now = latest(items, t);
  const labelW = cycle ? Math.min(300 * k, rx) : slot - 12 * k;
  const fs = (n > 4 ? 24 : 30) * k;
  // Cycle nodes on the left/right get their label outside, so the arrows never cross it.
  const labelBox = (i: number): { left: number; top: number; width: number; align: 'left' | 'right' | 'center' } => {
    const [x, y] = centers[i];
    const side = cycle ? Math.sin((2 * Math.PI * i) / n) : 0;
    const gap = D / 2 + 16 * k;
    if (side > 0.7) return { left: x + gap, top: y - fs * 0.62, width: Math.min(labelW, w - x - gap), align: 'left' };
    if (side < -0.7) {
      const width = Math.min(labelW, x - gap);
      return { left: x - gap - width, top: y - fs * 0.62, width, align: 'right' };
    }
    return { left: x - labelW / 2, top: y + D / 2 + 14 * k, width: labelW, align: 'center' };
  };

  const link = (a: Pt, b: Pt, i: number): string => {
    if (!cycle) return sketch.arrow([a[0] + D / 2 + 14 * k, a[1]], [b[0] - D / 2 - 14 * k, b[1]], seed + 50 + i, 18 * k);
    const ia = (2 * Math.PI * ((i - 1 + n) % n)) / n;
    const ib = (2 * Math.PI * (i % n)) / n + (i % n === 0 ? 2 * Math.PI : 0);
    const delta = (D / 2 + 16 * k) / Math.min(rx, ry);
    const from = onEllipse(cx, cy, rx * 1.02, ry * 1.02, ia + delta);
    const to = onEllipse(cx, cy, rx * 1.02, ry * 1.02, ib - delta);
    const mid = onEllipse(cx, cy, rx * 1.16, ry * 1.16, (ia + ib) / 2);
    return sketch.arc(from, mid, to, seed + 50 + i, 18 * k);
  };

  return (
    <>
      <InkLayer w={w} h={h}>
        {centers.map(([x, y], i) => (
          <Stroke key={`n${i}`} d={sketch.ellipse(x, y, D, D, seed + i * 3, { roughness: 1.3 })} p={easeOut(ramp(t, at(i), 500))} color={i === now ? color : INK_DIM} width={5 * k} />
        ))}
        {centers.map((c, i) => (i > 0 ? <Stroke key={`a${i}`} d={link(centers[i - 1], c, i)} p={easeOut(ramp(t, at(i) - 250, 420))} color={INK} width={4.5 * k} /> : null))}
        {cycle && <Stroke d={link(centers[n - 1], centers[0], n)} p={easeOut(ramp(t, at(n - 1) + 500, 500))} color={INK} width={4.5 * k} />}
      </InkLayer>
      {scene.steps.map((step, i) => {
        const [x, y] = centers[i];
        const icon = D * 0.5;
        return (
          <div key={i}>
            {step.icon ? (
              <div style={{ position: 'absolute', left: x - icon / 2, top: y - icon / 2 }}>
                <DrawnIcon name={step.icon} size={icon} color={i === now ? color : INK} p={easeInOut(ramp(t, at(i) + 200, 800))} />
              </div>
            ) : (
              <Reveal p={ramp(t, at(i) + 200, 400)} dy={0} style={{ position: 'absolute', left: x - D / 2, width: D, top: y - D * 0.28, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: D * 0.42, lineHeight: 1.3, color: i === now ? color : INK }}>
                {i + 1}
              </Reveal>
            )}
            <Reveal p={easeOut(ramp(t, at(i) + 250, 400))} dy={8 * k} style={{ position: 'absolute', left: labelBox(i).left, width: labelBox(i).width, top: labelBox(i).top, textAlign: labelBox(i).align, fontFamily: FONT, fontWeight: 700, fontSize: fs, lineHeight: 1.15, color: i === now ? INK : '#ffffffb3' }}>
              {step.label}
            </Reveal>
          </div>
        );
      })}
    </>
  );
};

/** Dated events on a hand-drawn axis, appearing as each one is mentioned. */
export const TimelineView = ({ scene, ctx }: { scene: TimelineScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, id } = ctx;
  const seed = seedOf(id);
  const n = scene.events.length;
  const axisY = h * 0.46;
  const left = 16 * k;
  const span = w - 32 * k;
  const slot = span / n;
  const now = latest(items, t);
  const at = (i: number) => items[i] ?? i * 900;
  return (
    <>
      <InkLayer w={w} h={h}>
        <Stroke d={sketch.arrow([left, axisY], [w - 8 * k, axisY], seed, 22 * k, { roughness: 0.9 })} p={easeOut(ramp(t, 0, 700))} color={INK_DIM} width={4 * k} />
        {scene.events.map((_, i) => {
          const x = left + slot * (i + 0.5);
          const pop = easeOut(ramp(t, at(i), 300));
          return pop > 0 ? <circle key={i} cx={x} cy={axisY} r={(i === now ? 15 : 11) * k * pop} fill={i === now ? color : INK} /> : null;
        })}
        {scene.events.map((_, i) => {
          const x = left + slot * (i + 0.5);
          return <Stroke key={`t${i}`} d={sketch.line([x, axisY - 34 * k], [x, axisY - 16 * k], seed + 10 + i, { roughness: 0.6 })} p={ramp(t, at(i) + 100, 250)} color={INK_DIM} width={3 * k} />;
        })}
      </InkLayer>
      {scene.events.map((ev, i) => {
        const x = left + slot * i;
        const dim = i === now ? 1 : 0.72;
        return (
          <div key={i} style={{ opacity: dim }}>
            <Reveal p={easeOut(ramp(t, at(i), 380))} dy={-12 * k} style={{ position: 'absolute', left: x, width: slot, top: axisY - 112 * k, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: (n > 4 ? 34 : 44) * k, color: i === now ? color : INK, whiteSpace: 'nowrap' }}>
              {ev.date}
            </Reveal>
            <Reveal p={easeOut(ramp(t, at(i) + 150, 400))} dy={12 * k} style={{ position: 'absolute', left: x + 6 * k, width: slot - 12 * k, top: axisY + 34 * k, textAlign: 'center', fontFamily: FONT, fontWeight: 600, fontSize: (n > 4 ? 22 : 27) * k, lineHeight: 1.18, color: INK }}>
              {ev.label}
            </Reveal>
          </div>
        );
      })}
    </>
  );
};

/** One to three big pictograms drawn stroke by stroke, each with its caption. */
export const IconsView = ({ scene, ctx }: { scene: IconsScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, id } = ctx;
  const seed = seedOf(id);
  const n = scene.items.length;
  const slot = w / n;
  const size = Math.min(slot * 0.5, h * 0.42, 230 * k);
  const ring = size * 1.5;
  const cy = h * 0.4;
  const now = latest(items, t);
  const at = (i: number) => items[i] ?? i * 900;
  return (
    <>
      <InkLayer w={w} h={h}>
        {scene.items.map((_, i) => (
          <Stroke key={i} d={sketch.ellipse(slot * (i + 0.5), cy, ring, ring, seed + i, { roughness: 1.4 })} p={easeOut(ramp(t, at(i), 550))} color={i === now ? color : INK_DIM} width={4 * k} opacity={0.8} />
        ))}
      </InkLayer>
      {scene.items.map((item, i) => (
        <div key={i}>
          <div style={{ position: 'absolute', left: slot * (i + 0.5) - size / 2, top: cy - size / 2 }}>
            <DrawnIcon name={item.icon} size={size} color={i === now ? color : INK} p={easeInOut(ramp(t, at(i) + 150, 1100))} strokeWidth={1.5} />
          </div>
          <Reveal p={easeOut(ramp(t, at(i) + 450, 400))} dy={10 * k} style={{ position: 'absolute', left: slot * i + 8 * k, width: slot - 16 * k, top: cy + ring / 2 + 22 * k, textAlign: 'center', fontFamily: FONT, fontWeight: 700, fontSize: (n > 2 ? 32 : 38) * k, lineHeight: 1.15, color: INK }}>
            {item.label}
          </Reveal>
        </div>
      ))}
    </>
  );
};
