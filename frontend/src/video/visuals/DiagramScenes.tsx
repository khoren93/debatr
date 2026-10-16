import type { MatrixScene, ScaleScene, VennScene } from '../../api/visuals';
import { DISPLAY_FONT, FONT } from '../constants';
import { INK, INK_DIM, backOut, easeOut, fitFont, ramp, seedOf, sketch, type Pt } from './draw';
import { InkLayer, Reveal, Stroke } from './Ink';
import { seriesColors, sideColors, type SceneCtx } from './scene';

const DEG = Math.PI / 180;
const STEP_TILT = 4 * DEG; // per argument more on one side
const MAX_TILT = 11 * DEG;
const DROP_MS = 420;

/** Damped step response 0 → 1: the beam overshoots and settles after a weight lands. */
const settle = (tau: number) => (tau <= 0 ? 0 : 1 - Math.exp(-tau / 260) * Math.cos(tau / 150));

/** A balance: arguments drop into the two pans as they are said and the beam tips over. */
export const ScaleView = ({ scene, ctx }: { scene: ScaleScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, id } = ctx;
  const seed = seedOf(id);
  const [leftC, rightC] = sideColors(ctx, [scene.left.label, scene.right.label]);
  const nl = scene.left.items.length;
  const at = (i: number) => items[i] ?? 500 + i * 800;

  // Beam angle (radians, > 0 = the right pan goes down) as a sum of settling steps.
  const landings = [...scene.left.items.map((_, i) => ({ t: at(i) + DROP_MS, side: -1 })), ...scene.right.items.map((_, i) => ({ t: at(nl + i) + DROP_MS, side: 1 }))].sort((a, b) => a.t - b.t);
  let angle = 0;
  let target = 0;
  let balance = 0;
  for (const landing of landings) {
    balance += landing.side;
    const next = Math.max(-MAX_TILT, Math.min(MAX_TILT, balance * STEP_TILT));
    angle += (next - target) * settle(t - landing.t);
    target = next;
  }
  const verdictAt = Math.max(0, ...landings.map((l) => l.t)) + 600;
  const final = scene.heavier === 'right' ? MAX_TILT : scene.heavier === 'left' ? -MAX_TILT : scene.heavier === 'even' ? 0 : target;
  angle += (final - target) * settle(t - verdictAt);
  const heavySide = final > 0 ? 'right' : final < 0 ? 'left' : null;

  const px = w / 2;
  const py = h * 0.74;
  const baseY = h - 6 * k;
  const L = w * 0.34;
  const panW = Math.min(w * 0.3, 360 * k);
  const postH = 30 * k;
  const fs = 27 * k;
  const chipW = panW - 16 * k;
  const chipLines = (text: string) => (text.length * fs * 0.52 > chipW - 28 * k ? 2 : 1);
  const chipH = (text: string) => chipLines(text) * fs * 1.18 + 22 * k;

  const pans = (['left', 'right'] as const).map((side) => {
    const sign = side === 'left' ? -1 : 1;
    const offset = side === 'left' ? 0 : nl;
    const nx = px + sign * L; // neutral end; the pan moves by (dx, dy) with the beam
    const dx = px + sign * L * Math.cos(angle) - nx;
    const dy = sign * L * Math.sin(angle);
    const plateY = py - postH;
    let stack = plateY - 6 * k;
    const chips = scene[side].items.map((item, i) => {
      const ch = chipH(item.text);
      stack -= ch;
      const top = stack;
      stack -= 10 * k;
      return { text: item.text, i, top, ch, start: at(offset + i) };
    });
    return { side, sign, nx, dx, dy, plateY, chips, label: scene[side].label, c: side === 'left' ? leftC : rightC, heavy: heavySide === side && t >= verdictAt };
  });

  return (
    <>
      <InkLayer w={w} h={h}>
        <Stroke d={sketch.line([px - 130 * k, baseY], [px + 130 * k, baseY], seed + 1, { roughness: 1 })} p={easeOut(ramp(t, 0, 400))} color={INK_DIM} width={5 * k} />
        <Stroke
          d={sketch.polyline(
            [
              [px - 60 * k, baseY],
              [px, py],
              [px + 60 * k, baseY],
            ],
            seed + 2,
            { roughness: 0.9 },
          )}
          p={easeOut(ramp(t, 100, 450))}
          color={INK}
          width={5 * k}
        />
        <g transform={`rotate(${(angle / DEG).toFixed(3)} ${px} ${py})`}>
          <Stroke d={sketch.line([px - L, py], [px + L, py], seed + 4, { roughness: 0.7, bowing: 0.3 })} p={easeOut(ramp(t, 150, 450))} color={INK} width={7 * k} />
        </g>
        <circle cx={px} cy={py} r={10 * k} fill={color} opacity={ramp(t, 300, 200)} />
        {pans.map(({ side, sign, nx, dx, dy, plateY, chips, c, heavy }) => (
          <g key={side} transform={`translate(${dx.toFixed(2)} ${dy.toFixed(2)})`}>
            <Stroke d={sketch.line([nx, py], [nx, plateY], seed + sign * 3, { roughness: 0.6 })} p={easeOut(ramp(t, 250, 300))} color={INK} width={4 * k} />
            <Stroke
              d={sketch.polyline(
                [
                  [nx - panW / 2, plateY - 12 * k],
                  [nx - panW / 2 + 16 * k, plateY],
                  [nx + panW / 2 - 16 * k, plateY],
                  [nx + panW / 2, plateY - 12 * k],
                ],
                seed + sign * 5,
                { roughness: 0.8 },
              )}
              p={easeOut(ramp(t, 350, 450))}
              color={c}
              width={5 * k}
            />
            {chips.map(({ i, top, ch, start }) => (
              <Stroke key={i} d={sketch.rect(nx - chipW / 2, top, chipW, ch, seed + sign * 11 + i, { roughness: 0.9 })} p={easeOut(ramp(t, start + DROP_MS - 60, 320))} color={c} width={3 * k} opacity={0.9} />
            ))}
            {heavy && <Stroke d={sketch.line([nx - panW * 0.32, py + 74 * k], [nx + panW * 0.32, py + 70 * k], seed + sign * 17, { roughness: 1.3 })} p={easeOut(ramp(t, verdictAt + 250, 400))} color={c} width={6 * k} />}
          </g>
        ))}
      </InkLayer>
      {pans.map(({ side, nx, dx, dy, chips, label, c }) => (
        <div key={side}>
          {chips.map(({ text, i, top, ch, start }) => {
            const p = ramp(t, start, DROP_MS);
            if (p <= 0) return null;
            const fall = -((1 - p) ** 2) * 150 * k;
            return (
              <div key={i} style={{ position: 'absolute', left: nx - chipW / 2 + dx, top: top + dy + fall, width: chipW, height: ch, opacity: Math.min(1, p * 3), display: 'flex', alignItems: 'center', justifyContent: 'center', padding: `0 ${14 * k}px`, boxSizing: 'border-box', textAlign: 'center', fontFamily: FONT, fontWeight: 700, fontSize: fs, lineHeight: 1.18, color: INK }}>
                {text}
              </div>
            );
          })}
          <Reveal p={easeOut(ramp(t, side === 'left' ? 300 : 450, 400))} dy={0} style={{ position: 'absolute', left: nx - panW / 2 + dx, top: py + 18 * k + dy, width: panW, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: 36 * k, lineHeight: 1.2, color: c, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {label}
          </Reveal>
        </div>
      ))}
    </>
  );
};

/** 2×2 matrix: two criteria as hand-drawn axes, options pop up where the speaker places them. */
export const MatrixView = ({ scene, ctx }: { scene: MatrixScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, id } = ctx;
  const seed = seedOf(id);
  const left = 62 * k;
  const right = w - 12 * k;
  const top = 12 * k;
  const bottom = h - 58 * k;
  const midX = (left + right) / 2;
  const midY = (top + bottom) / 2;
  const at = (i: number) => items[i] ?? 700 + i * 700;
  const inner = 34 * k;
  const pos = (x: number, y: number): Pt => [left + inner + (x / 10) * (right - left - inner * 2), bottom - inner - (y / 10) * (bottom - top - inner * 2)];
  const corner = (i: number) => {
    const isRight = i % 2 === 1;
    const isBottom = i >= 2;
    return { left: isRight ? midX + 18 * k : left + 18 * k, width: (right - left) / 2 - 36 * k, top: isBottom ? bottom - 44 * k : top + 10 * k, textAlign: isRight ? ('right' as const) : ('left' as const) };
  };
  return (
    <>
      <InkLayer w={w} h={h}>
        <Stroke d={sketch.arrow([left, bottom], [right, bottom], seed, 20 * k, { roughness: 0.8 })} p={easeOut(ramp(t, 0, 600))} color={INK} width={4.5 * k} />
        <Stroke d={sketch.arrow([left, bottom], [left, top], seed + 1, 20 * k, { roughness: 0.8 })} p={easeOut(ramp(t, 150, 600))} color={INK} width={4.5 * k} />
        <Stroke d={sketch.line([midX, top + 10 * k], [midX, bottom - 10 * k], seed + 2, { roughness: 1.2 })} p={easeOut(ramp(t, 350, 500))} color={INK_DIM} width={2.5 * k} opacity={0.6} />
        <Stroke d={sketch.line([left + 10 * k, midY], [right - 10 * k, midY], seed + 3, { roughness: 1.2 })} p={easeOut(ramp(t, 450, 500))} color={INK_DIM} width={2.5 * k} opacity={0.6} />
        {scene.items.map((item, i) => {
          const [x, y] = pos(item.x, item.y);
          const pop = backOut(ramp(t, at(i), 380));
          if (pop <= 0) return null;
          return (
            <g key={i}>
              <circle cx={x} cy={y} r={Math.max(0, 13 * k * pop)} fill={item.highlight ? color : INK} />
              {item.highlight && <Stroke d={sketch.ellipse(x, y, 58 * k, 54 * k, seed + 10 + i, { roughness: 1.3 })} p={easeOut(ramp(t, at(i) + 200, 450))} color={color} width={4 * k} />}
            </g>
          );
        })}
      </InkLayer>
      <Reveal p={easeOut(ramp(t, 400, 400))} dy={0} style={{ position: 'absolute', right: 0, top: bottom + 14 * k, fontFamily: FONT, fontWeight: 800, fontSize: 24 * k, letterSpacing: 2 * k, textTransform: 'uppercase', color: INK_DIM, whiteSpace: 'nowrap' }}>
        {scene.x_axis} →
      </Reveal>
      <Reveal p={easeOut(ramp(t, 550, 400))} dy={0} style={{ position: 'absolute', left: 0, top, height: bottom - top, width: 40 * k, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
        <div style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', fontFamily: FONT, fontWeight: 800, fontSize: 24 * k, letterSpacing: 2 * k, textTransform: 'uppercase', color: INK_DIM, whiteSpace: 'nowrap', textAlign: 'right', maxHeight: bottom - top }}>{scene.y_axis} →</div>
      </Reveal>
      {scene.quadrants.map((label, i) =>
        label ? (
          <Reveal key={`q${i}`} p={ramp(t, 600 + i * 100, 400)} dy={0} style={{ position: 'absolute', ...corner(i), fontFamily: FONT, fontWeight: 700, fontSize: 22 * k, letterSpacing: 1.5 * k, textTransform: 'uppercase', color: '#ffffff66', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {label}
          </Reveal>
        ) : null,
      )}
      {scene.items.map((item, i) => {
        const [x, y] = pos(item.x, item.y);
        const flip = x > left + (right - left) * 0.68;
        const labelW = 300 * k;
        const gap = (item.highlight ? 40 : 26) * k; // clear of the marker ring
        return (
          <Reveal key={i} p={easeOut(ramp(t, at(i) + 80, 350))} dy={8 * k} style={{ position: 'absolute', left: flip ? x - gap - labelW : x + gap, width: labelW, top: y - 20 * k, textAlign: flip ? 'right' : 'left', fontFamily: FONT, fontWeight: 800, fontSize: 30 * k, lineHeight: 1.12, color: item.highlight ? color : INK, textShadow: '0 2px 10px #0b1020' }}>
            {item.label}
          </Reveal>
        );
      })}
    </>
  );
};

/** Two or three overlapping circles; the shared part lights up in the speaker colour. */
export const VennView = ({ scene, ctx }: { scene: VennScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, id } = ctx;
  const seed = seedOf(id);
  const n = scene.sets.length;
  const colors = seriesColors(color, n + 1).slice(1);
  const three = n === 3;
  const r = three ? Math.min((h - 60 * k) / 2.9, w * 0.2) : Math.min((h - 130 * k) / 2, w * 0.21);
  const cx = w / 2;
  const cy = three ? 30 * k + r + 0.6 * r : 56 * k + r;
  const c = 0.6 * r;
  const centers: Pt[] = three
    ? [
        [cx, cy - c],
        [cx - c * Math.cos(30 * DEG), cy + c / 2],
        [cx + c * Math.cos(30 * DEG), cy + c / 2],
      ]
    : [
        [cx - r * 0.55, cy],
        [cx + r * 0.55, cy],
      ];
  const at = (i: number) => items[i] ?? 400 + i * 900;
  const overlapAt = scene.overlap ? at(n) : Math.max(...centers.map((_, i) => at(i))) + 700;
  const lit = easeOut(ramp(t, overlapAt, 500));
  const fs = 34 * k;
  // Labels sit outside the circles: above them (two sets) or beside them (three).
  const labelBox = (i: number) => {
    const [x, y] = centers[i];
    if (!three) return { left: i === 0 ? 0 : cx, width: w / 2, top: 0, textAlign: 'center' as const, x: i === 0 ? x - r * 0.25 : x + r * 0.25 };
    const width = Math.max(120 * k, i === 2 ? w - (x + r + 18 * k) : x - r - 18 * k);
    const top = i === 0 ? y - r * 0.55 - fs * 0.6 : y - fs * 0.6; // the top set: clear of the lower circles
    if (i === 2) return { left: x + r + 18 * k, width, top, textAlign: 'left' as const, x: 0 };
    return { left: x - r - 18 * k - width, width, top, textAlign: 'right' as const, x: 0 };
  };
  const overlapBox = three ? { left: centers[0][0] + r + 18 * k, top: centers[0][1] - r * 0.55 - fs * 0.6, width: w - (centers[0][0] + r + 18 * k) } : { left: w * 0.15, top: cy + r + 16 * k, width: w * 0.7 };
  const arrowFrom: Pt = three ? [overlapBox.left - 8 * k, overlapBox.top + fs * 0.6] : [cx, overlapBox.top - 4 * k];
  const arrowTo: Pt = three ? [cx + r * 0.12, cy - r * 0.05] : [cx, cy + r * 0.42];
  const arrowMid: Pt = three ? [(arrowFrom[0] + arrowTo[0]) / 2, arrowFrom[1] + r * 0.25] : [cx + r * 0.25, (arrowFrom[1] + arrowTo[1]) / 2];
  return (
    <>
      <InkLayer w={w} h={h}>
        <defs>
          {centers.map(([x, y], i) => (
            <clipPath key={i} id={`${id}-set${i}`}>
              <circle cx={x} cy={y} r={r} />
            </clipPath>
          ))}
        </defs>
        {centers.map(([x, y], i) => (
          <circle key={`f${i}`} cx={x} cy={y} r={r} fill={colors[i]} fillOpacity={0.1 * easeOut(ramp(t, at(i) + 200, 500))} />
        ))}
        {lit > 0 && (
          <g clipPath={`url(#${id}-set0)`}>
            {three ? (
              <g clipPath={`url(#${id}-set1)`}>
                <circle cx={centers[2][0]} cy={centers[2][1]} r={r} fill={color} fillOpacity={0.55 * lit} />
              </g>
            ) : (
              <circle cx={centers[1][0]} cy={centers[1][1]} r={r} fill={color} fillOpacity={0.55 * lit} />
            )}
          </g>
        )}
        {centers.map(([x, y], i) => (
          <Stroke key={`s${i}`} d={sketch.ellipse(x, y, r * 2, r * 2, seed + i * 5, { roughness: 1.1 })} p={easeOut(ramp(t, at(i), 650))} color={colors[i]} width={5 * k} />
        ))}
        {scene.overlap && <Stroke d={sketch.arc(arrowFrom, arrowMid, arrowTo, seed + 40, 18 * k)} p={easeOut(ramp(t, overlapAt + 150, 450))} color={INK} width={4 * k} />}
      </InkLayer>
      {scene.sets.map((set, i) => {
        const box = labelBox(i);
        return (
          <Reveal key={i} p={easeOut(ramp(t, at(i) + 150, 400))} dy={8 * k} style={{ position: 'absolute', left: box.left, width: box.width, top: box.top, textAlign: box.textAlign, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: three ? fitFont(set.label, box.width, 2, fs, 22 * k) : fs, lineHeight: 1.15, color: colors[i], ...(three ? {} : { transform: `translateX(${box.x - (box.left + box.width / 2)}px)`, whiteSpace: 'nowrap' }) }}>
            {set.label}
          </Reveal>
        );
      })}
      {scene.overlap && (
        <Reveal p={easeOut(ramp(t, overlapAt, 400))} dy={10 * k} style={{ position: 'absolute', left: overlapBox.left, width: overlapBox.width, top: overlapBox.top, textAlign: three ? 'left' : 'center', fontFamily: FONT, fontWeight: 800, fontSize: fitFont(scene.overlap, overlapBox.width, 2, 36 * k, 24 * k), lineHeight: 1.15, color }}>
          {scene.overlap}
        </Reveal>
      )}
    </>
  );
};
