import type { BarsScene, LineScene, PieScene, ProportionScene, StatScene } from '../../api/visuals';
import { DISPLAY_FONT, FONT } from '../constants';
import { INK, INK_DIM, compactNumber, easeInOut, easeOut, formatNumber, ramp, seedOf, sketch, withUnit, type Pt } from './draw';
import { DrawnIcon, InkLayer, Reveal, Stroke } from './Ink';
import { seriesColors, type SceneCtx } from './scene';

const GLYPH = 0.58; // average digit width in em for the display font

/** One big number that counts up, a marker underline, an optional pictogram and trend arrow. */
export const StatView = ({ scene, ctx }: { scene: StatScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, locale, id } = ctx;
  const seed = seedOf(id);
  const count = easeOut(ramp(t, 150, 1100));
  const final = `${scene.prefix}${formatNumber(scene.value, locale)}${scene.suffix}`;
  const shown = `${scene.prefix}${formatNumber(scene.value * count, locale, scene.value)}${scene.suffix}`;
  const iconSize = scene.icon ? Math.min(150 * k, h * 0.3) : 0;
  const arrowW = scene.trend ? 70 * k : 0;
  const gap = 36 * k;
  const room = w * 0.92 - iconSize - arrowW - (iconSize ? gap : 0) - (arrowW ? gap : 0);
  const fs = Math.min(220 * k, room / Math.max(2, final.length * GLYPH), h * 0.42);
  const textW = final.length * fs * GLYPH;
  const rowW = iconSize + (iconSize ? gap : 0) + textW + (arrowW ? gap + arrowW : 0);
  const x0 = (w - rowW) / 2;
  const numX = x0 + iconSize + (iconSize ? gap : 0);
  const cy = h * 0.4;
  const underY = cy + fs * 0.52;
  const arrowX = numX + textW + gap + arrowW / 2;
  const arrowA: Pt = scene.trend === 'down' ? [arrowX, cy - fs * 0.32] : [arrowX, cy + fs * 0.32];
  const arrowB: Pt = scene.trend === 'down' ? [arrowX, cy + fs * 0.32] : [arrowX, cy - fs * 0.32];
  return (
    <>
      <InkLayer w={w} h={h}>
        <Stroke d={sketch.line([numX - 12 * k, underY], [numX + textW + 12 * k, underY + 6 * k], seed, { roughness: 1.6, bowing: 2 })} p={easeOut(ramp(t, 900, 600))} color={color} width={7 * k} />
        {scene.trend && <Stroke d={sketch.arrow(arrowA, arrowB, seed + 5, 26 * k, { roughness: 0.9 })} p={easeOut(ramp(t, 1100, 500))} color={color} width={7 * k} />}
      </InkLayer>
      {scene.icon && (
        <div style={{ position: 'absolute', left: x0, top: cy - iconSize / 2 }}>
          <DrawnIcon name={scene.icon} size={iconSize} color={INK} p={easeInOut(ramp(t, 0, 1100))} strokeWidth={1.5} />
        </div>
      )}
      <div style={{ position: 'absolute', left: numX - 200, width: textW + 400, top: cy - fs * 0.62, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: fs, lineHeight: 1.1, color, whiteSpace: 'nowrap', letterSpacing: -fs * 0.02 }}>{shown}</div>
      <Reveal p={easeOut(ramp(t, 500, 500))} style={{ position: 'absolute', left: w * 0.06, right: w * 0.06, top: underY + 34 * k, textAlign: 'center', fontFamily: FONT, fontWeight: 700, fontSize: 40 * k, lineHeight: 1.2, color: INK }}>
        {scene.label}
      </Reveal>
    </>
  );
};

/** Bars that grow one after another; hachure fill like a marker sketch. */
export const BarsView = ({ scene, ctx }: { scene: BarsScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, locale, id } = ctx;
  const seed = seedOf(id);
  const n = scene.items.length;
  const max = Math.max(0, ...scene.items.map((i) => i.value)) || 1;
  const longUnit = scene.unit.length > 3;
  const suffix = longUnit ? '' : scene.unit;
  const labelH = 70 * k;
  const top = (longUnit ? 44 : 0) * k + 58 * k;
  const bottom = h - labelH;
  const chartH = bottom - top;
  const slot = w / n;
  const barW = Math.min(150 * k, slot * 0.58);
  const anyHighlight = scene.items.some((i) => i.highlight);
  return (
    <>
      {longUnit && <div style={{ position: 'absolute', left: 0, top: 0, fontFamily: FONT, fontSize: 24 * k, fontWeight: 600, color: INK_DIM }}>{scene.unit}</div>}
      <InkLayer w={w} h={h}>
        <defs>
          {scene.items.map((item, i) => {
            const full = Math.max(4 * k, (Math.max(0, item.value) / max) * chartH);
            const g = easeOut(ramp(t, 300 + i * 200, 700));
            return (
              <clipPath key={i} id={`${id}-bar${i}`}>
                <rect x={slot * i} y={bottom - full * g - 6} width={slot} height={full * g + 12} />
              </clipPath>
            );
          })}
        </defs>
        {scene.items.map((item, i) => {
          const full = Math.max(4 * k, (Math.max(0, item.value) / max) * chartH);
          const x = slot * i + (slot - barW) / 2;
          const [fill, edge] = sketch.hatched(x, bottom - full, barW, full, seed + i * 7, 13 * k);
          const c = !anyHighlight || item.highlight ? color : INK_DIM;
          return (
            <g key={i} clipPath={`url(#${id}-bar${i})`}>
              <path d={fill} fill="none" stroke={c} strokeWidth={3.2 * k} strokeLinecap="round" opacity={0.85} />
              <path d={edge} fill="none" stroke={c} strokeWidth={4 * k} strokeLinecap="round" strokeLinejoin="round" />
            </g>
          );
        })}
        <Stroke d={sketch.line([4 * k, bottom], [w - 4 * k, bottom], seed + 99, { roughness: 0.8 })} p={easeOut(ramp(t, 0, 500))} color={INK} width={4 * k} />
      </InkLayer>
      {scene.items.map((item, i) => {
        const full = Math.max(4 * k, (Math.max(0, item.value) / max) * chartH);
        const g = easeOut(ramp(t, 300 + i * 200, 700));
        const c = !anyHighlight || item.highlight ? color : INK;
        return (
          <div key={i}>
            <div style={{ position: 'absolute', left: slot * i, width: slot, top: bottom - full * g - 50 * k, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: 34 * k, color: c, opacity: g > 0 ? 1 : 0, whiteSpace: 'nowrap' }}>
              {withUnit(compactNumber(item.value * g, locale), suffix)}
            </div>
            <Reveal p={ramp(t, 200 + i * 200, 400)} dy={8} style={{ position: 'absolute', left: slot * i + 6 * k, width: slot - 12 * k, top: bottom + 12 * k, textAlign: 'center', fontFamily: FONT, fontWeight: 600, fontSize: (n > 4 ? 22 : 26) * k, lineHeight: 1.15, color: INK }}>
              {item.label}
            </Reveal>
          </div>
        );
      })}
    </>
  );
};

/** A trend line drawn left to right; dots appear as the pen passes, the last one pulses. */
export const LineView = ({ scene, ctx }: { scene: LineScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, locale, id } = ctx;
  const seed = seedOf(id);
  const pts = scene.points;
  const n = pts.length;
  const values = pts.map((p) => p.value);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (hi === lo) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.14;
  const left = 40 * k;
  const right = w - 70 * k;
  const top = 64 * k;
  const bottom = h - 58 * k;
  const xy = pts.map((p, i): Pt => [left + ((right - left) * i) / (n - 1), bottom - ((p.value - lo + pad) / (hi - lo + 2 * pad)) * (bottom - top)]);
  const drawn = easeInOut(ramp(t, 400, 1900));
  const reached = drawn * (n - 1); // index the pen has passed
  const every = n <= 7 ? 1 : Math.ceil(n / 6);
  const pulse = ((t - 2300) % 1300) / 1300;
  const last = xy[n - 1];
  const suffix = scene.unit.length <= 3 ? scene.unit : '';
  return (
    <>
      <InkLayer w={w} h={h}>
        <Stroke d={sketch.line([4 * k, bottom + 18 * k], [w - 4 * k, bottom + 18 * k], seed + 1, { roughness: 0.7 })} p={easeOut(ramp(t, 0, 500))} color={INK_DIM} width={3 * k} />
        <Stroke d={sketch.polyline(xy, seed, { roughness: 0.6, bowing: 0.4 })} p={drawn} color={color} width={7 * k} />
        {xy.map(([x, y], i) => (reached >= i - 0.02 ? <circle key={i} cx={x} cy={y} r={(pts[i].highlight || i === n - 1 ? 10 : 7) * k} fill={pts[i].highlight || i === n - 1 ? color : INK} /> : null))}
        {t > 2300 && <circle cx={last[0]} cy={last[1]} r={(10 + 26 * pulse) * k} fill="none" stroke={color} strokeWidth={3 * k} opacity={1 - pulse} />}
      </InkLayer>
      {pts.map((p, i) =>
        i % every === 0 || i === n - 1 ? (
          <Reveal key={`x${i}`} p={ramp(t, 200 + i * 60, 400)} dy={6} style={{ position: 'absolute', left: xy[i][0] - 80 * k, width: 160 * k, top: bottom + 26 * k, textAlign: 'center', fontFamily: FONT, fontWeight: 600, fontSize: 22 * k, color: INK_DIM, whiteSpace: 'nowrap' }}>
            {p.label}
          </Reveal>
        ) : null,
      )}
      {pts.map((p, i) =>
        (i === 0 || i === n - 1 || p.highlight) && reached >= i - 0.02 ? (
          <div key={`v${i}`} style={{ position: 'absolute', left: xy[i][0] - 120 * k, width: 240 * k, top: xy[i][1] - 62 * k, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: (i === n - 1 ? 38 : 30) * k, color: i === n - 1 || p.highlight ? color : INK, whiteSpace: 'nowrap' }}>
            {withUnit(formatNumber(p.value, locale), suffix)}
          </div>
        ) : null,
      )}
      {scene.unit.length > 3 && <div style={{ position: 'absolute', left: 0, top: 0, fontFamily: FONT, fontSize: 24 * k, fontWeight: 600, color: INK_DIM }}>{scene.unit}</div>}
    </>
  );
};

const arcPath = (cx: number, cy: number, r: number, a0: number, a1: number) => {
  const [x0, y0] = [cx + r * Math.sin(a0), cy - r * Math.cos(a0)];
  const [x1, y1] = [cx + r * Math.sin(a1), cy - r * Math.cos(a1)];
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
};

/** Donut whose slices sweep in one by one, with a legend of shares. */
export const PieView = ({ scene, ctx }: { scene: PieScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, locale, id } = ctx;
  const seed = seedOf(id);
  const total = scene.items.reduce((s, i) => s + i.value, 0) || 1;
  const colors = seriesColors(color, scene.items.length);
  const narrow = w / h < 1.45;
  const R = narrow ? Math.min(h * 0.27, w * 0.3) : Math.min(h * 0.4, w * 0.24);
  const cx = narrow ? w / 2 : w * 0.28;
  const cy = narrow ? R + 16 * k : h / 2;
  const sw = R * 0.42;
  const mid = R - sw / 2;
  const gapA = 0.025;
  const focus = scene.items.findIndex((i) => i.highlight);
  const main = focus >= 0 ? focus : scene.items.reduce((best, i, idx) => (i.value > scene.items[best].value ? idx : best), 0);
  const showValue = Boolean(scene.unit) && scene.unit !== '%';
  const ends = scene.items.map((_, i) => scene.items.slice(0, i + 1).reduce((s, it) => s + it.value, 0));
  const slices = scene.items.map((item, i) => {
    const a0 = ((ends[i] - item.value) / total) * Math.PI * 2;
    const a1 = (ends[i] / total) * Math.PI * 2;
    return { item, a0: a0 + gapA, a1: Math.max(a0 + gapA + 0.01, a1 - gapA), share: item.value / total, start: 300 + i * 380, c: colors[i] };
  });
  const done = 300 + scene.items.length * 380 + 300;
  const legendX = narrow ? w * 0.12 : cx + R + 70 * k;
  const legendY = narrow ? cy + R + 40 * k : cy - (scene.items.length * 64 * k) / 2;
  return (
    <>
      <InkLayer w={w} h={h}>
        <Stroke d={sketch.ellipse(cx, cy, (R + 14 * k) * 2, (R + 14 * k) * 2, seed, { roughness: 1.2 })} p={easeOut(ramp(t, 0, 700))} color={INK_DIM} width={3 * k} />
        {slices.map((s, i) => (
          <path key={i} d={arcPath(cx, cy, mid, s.a0, s.a1)} fill="none" stroke={s.c} strokeWidth={sw} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - easeOut(ramp(t, s.start, 550))} opacity={t >= s.start ? 1 : 0} />
        ))}
      </InkLayer>
      <Reveal p={ramp(t, done, 400)} dy={0} style={{ position: 'absolute', left: cx - R, width: R * 2, top: cy - R * 0.24, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: R * 0.4, lineHeight: 1.2, color: slices[main].c }}>
        {Math.round(slices[main].share * 100)}%
      </Reveal>
      {slices.map((s, i) => (
        <Reveal key={i} p={ramp(t, s.start, 400)} dy={10} style={{ position: 'absolute', left: legendX, right: narrow ? w * 0.12 : 0, top: legendY + i * 64 * k, display: 'flex', alignItems: 'center', gap: 18 * k, fontFamily: FONT, fontSize: 30 * k, fontWeight: 600, color: INK }}>
          <span style={{ width: 22 * k, height: 22 * k, borderRadius: 6 * k, background: s.c, flexShrink: 0 }} />
          <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden' }}>{s.item.label}</span>
          <span style={{ fontFamily: DISPLAY_FONT, fontWeight: 800, color: s.c }}>{showValue ? withUnit(compactNumber(s.item.value, locale), scene.unit) : `${Math.round(s.share * 100)}%`}</span>
        </Reveal>
      ))}
    </>
  );
};

/** Isotype grid: N pictograms, the first `count` light up in the speaker colour ("1 in 4"). */
export const ProportionView = ({ scene, ctx }: { scene: ProportionScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color } = ctx;
  const total = Math.round(scene.total);
  const count = Math.round(scene.count);
  const cols = total <= 10 ? total : 10;
  const rows = Math.ceil(total / cols);
  const gridW = w * 0.86;
  const gridH = h * 0.56;
  const cell = Math.min(gridW / cols, gridH / rows, 210 * k);
  const icon = cell * 0.78;
  const x0 = (w - cell * cols) / 2;
  const y0 = Math.max(0, (h - (rows * cell + 130 * k)) / 2);
  const step = Math.min(35, 900 / total);
  const lit = Math.min(1300, step * total + 450);
  const litStep = Math.min(140, 1000 / Math.max(1, count));
  const name = scene.icon ?? 'person';
  return (
    <>
      {Array.from({ length: total }).map((_, i) => {
        const on = i < count ? easeOut(ramp(t, lit + i * litStep, 450)) : 0;
        return (
          <div key={i} style={{ position: 'absolute', left: x0 + (i % cols) * cell + (cell - icon) / 2, top: y0 + Math.floor(i / cols) * cell + (cell - icon) / 2 }}>
            <div style={{ position: 'absolute', opacity: on > 0 ? 0.25 : 1 }}>
              <DrawnIcon name={name} size={icon} color={INK_DIM} p={ramp(t, i * step, 500)} strokeWidth={1.4} />
            </div>
            {on > 0 && (
              <div style={{ position: 'absolute' }}>
                <DrawnIcon name={name} size={icon} color={color} p={on} strokeWidth={2} fill={on >= 1 ? `${color}40` : undefined} />
              </div>
            )}
          </div>
        );
      })}
      <Reveal p={ramp(t, lit, 500)} style={{ position: 'absolute', left: 0, right: 0, top: y0 + rows * cell + 24 * k, display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 24 * k, fontFamily: FONT, color: INK }}>
        <span style={{ fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: 84 * k, color, whiteSpace: 'nowrap' }}>
          {count} / {total}
        </span>
        <span style={{ fontSize: 36 * k, fontWeight: 700, lineHeight: 1.2, maxWidth: w * 0.6 }}>{scene.label}</span>
      </Reveal>
    </>
  );
};
