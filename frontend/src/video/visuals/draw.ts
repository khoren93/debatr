import rough from 'roughjs';
import type { Options } from 'roughjs/bin/core';

/**
 * Hand-drawn ("marker on a dark board") geometry for the visual scenes.
 *
 * Every shape is generated with a fixed seed, so the same frame always gets the same wobble —
 * random seeds would make the strokes jitter from frame to frame. Shapes are returned as SVG
 * path data and animated with `pathLength=1` + `stroke-dashoffset` (see Ink.tsx).
 */

const gen = rough.generator();

export const INK = '#F4F6FB';
export const INK_DIM = '#ffffff8c';

export type Pt = [number, number];

export const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
/** 0 → 1 between `start` and `start + dur` (ms). */
export const ramp = (t: number, start: number, dur: number) => clamp01((t - start) / Math.max(1, dur));
export const easeOut = (x: number) => 1 - (1 - x) ** 3;
export const easeInOut = (x: number) => (x < 0.5 ? 4 * x ** 3 : 1 - (-2 * x + 2) ** 3 / 2);
export const backOut = (x: number) => {
  const c1 = 1.4;
  return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2;
};

/** Stable 31-bit seed from a string (visual id + element). */
export const seedOf = (key: string): number => {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 1) || 1;
};

const opts = (seed: number, o?: Options): Options => ({ seed, roughness: 1.1, bowing: 0.8, strokeWidth: 1, preserveVertices: true, ...o });

const outline = (drawable: ReturnType<typeof gen.line>) =>
  drawable.sets
    .filter((s) => s.type === 'path')
    .map((s) => gen.opsToPath(s, 2))
    .join(' ');

export const sketch = {
  line: (a: Pt, b: Pt, seed: number, o?: Options) => outline(gen.line(a[0], a[1], b[0], b[1], opts(seed, o))),
  polyline: (pts: Pt[], seed: number, o?: Options) => outline(gen.linearPath(pts, opts(seed, o))),
  curve: (pts: Pt[], seed: number, o?: Options) => outline(gen.curve(pts, opts(seed, o))),
  rect: (x: number, y: number, w: number, h: number, seed: number, o?: Options) => outline(gen.rectangle(x, y, w, h, opts(seed, o))),
  ellipse: (cx: number, cy: number, w: number, h: number, seed: number, o?: Options) => outline(gen.ellipse(cx, cy, w, h, opts(seed, o))),
  /** Line with an open arrow head at `b`. */
  arrow: (a: Pt, b: Pt, seed: number, head = 18, o?: Options) => {
    const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
    const wing = (side: number): Pt => [b[0] - head * Math.cos(angle + side * 0.5), b[1] - head * Math.sin(angle + side * 0.5)];
    return [sketch.line(a, b, seed, o), sketch.polyline([wing(1), b, wing(-1)], seed + 1, { ...o, roughness: 0.6 })].join(' ');
  },
  /** Curved arrow through a control point (cycles). */
  arc: (a: Pt, mid: Pt, b: Pt, seed: number, head = 18, o?: Options) => {
    const angle = Math.atan2(b[1] - mid[1], b[0] - mid[0]);
    const wing = (side: number): Pt => [b[0] - head * Math.cos(angle + side * 0.5), b[1] - head * Math.sin(angle + side * 0.5)];
    return [sketch.curve([a, mid, b], seed, o), sketch.polyline([wing(1), b, wing(-1)], seed + 1, { ...o, roughness: 0.6 })].join(' ');
  },
  check: (x: number, y: number, size: number, seed: number) =>
    sketch.polyline(
      [
        [x, y + size * 0.55],
        [x + size * 0.38, y + size * 0.92],
        [x + size, y + size * 0.05],
      ],
      seed,
      { roughness: 0.9 },
    ),
  /** Hachure-filled rectangle: `[fill, outline]` path data (bars). */
  hatched: (x: number, y: number, w: number, h: number, seed: number, gap: number) => {
    const d = gen.rectangle(x, y, w, h, opts(seed, { fill: '#fff', fillStyle: 'hachure', hachureGap: gap, hachureAngle: -41, fillWeight: Math.max(1.5, gap / 3.2) }));
    const fill = d.sets.filter((s) => s.type === 'fillSketch').map((s) => gen.opsToPath(s, 2)).join(' ');
    return [fill, outline(d)] as const;
  },
};

/** Point on an ellipse (angle 0 = top, clockwise). */
export const onEllipse = (cx: number, cy: number, rx: number, ry: number, angle: number): Pt => [cx + rx * Math.sin(angle), cy - ry * Math.cos(angle)];

const decimalsOf = (n: number) => (Number.isInteger(n) ? 0 : Math.min(2, (String(n).split('.')[1] ?? '').length));

/** Locale-aware number for the scenes; `like` fixes the decimals (count-up animations). */
export const formatNumber = (value: number, locale: string, like = value): string => {
  const digits = decimalsOf(like);
  try {
    return new Intl.NumberFormat(locale || 'en', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  } catch {
    return value.toFixed(digits);
  }
};

/** "40%", "3×" stay glued; longer units get a thin space ("2 $/W", "38 h"). */
export const withUnit = (value: string, unit: string): string => (!unit ? value : unit.length <= 1 || /^[%‰×x]$/.test(unit) ? `${value}${unit}` : `${value}\u2009${unit}`);

/** Short form for axis/value labels: 1.2K, 3.4M (keeps small numbers as they are). */
export const compactNumber = (value: number, locale: string): string => {
  if (Math.abs(value) < 10_000) return formatNumber(Math.round(value * 100) / 100, locale);
  try {
    return new Intl.NumberFormat(locale || 'en', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
  } catch {
    return String(Math.round(value));
  }
};

/** Font size that keeps `text` on about `lines` lines in `width` px (average glyph 0.55em). */
export const fitFont = (text: string, width: number, lines: number, max: number, min: number) =>
  Math.max(min, Math.min(max, (width * lines) / (Math.max(1, text.length) * 0.55)));

/** Rows `text` takes at `size` px in `width` px, by the average glyph (as `fitFont`; the size it
 *  picks for n rows gives n, not n + 1 by a rounding error). */
export const rowsAt = (text: string, size: number, width: number) => Math.max(1, Math.ceil((text.length * 0.55 * size) / width - 1e-6));
