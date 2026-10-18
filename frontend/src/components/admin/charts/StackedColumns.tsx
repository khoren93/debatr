import { useState, type KeyboardEvent } from 'react';
import { AXIS_TEXT, BASELINE, GRID } from './palette';
import { labelIndexes, niceTicks } from './scale';
import { ChartTooltip } from './ChartTooltip';
import { useWidth } from './useWidth';

export interface ColumnSeries {
  key: string;
  label: string;
  color: string;
  values: number[];
}

interface StackedColumnsProps {
  /** Bottom to top. */
  series: ColumnSeries[];
  labels: string[];
  axisLabels: string[];
  format: (value: number) => string;
  ariaLabel: string;
  height?: number;
}

const PAD = { left: 36, right: 8, top: 10, bottom: 24 };
const GAP = 2; // surface gap between stacked segments
const RADIUS = 4;

/** A column with a rounded data end and a square foot. */
const topRounded = (x: number, y: number, w: number, h: number) => {
  const r = Math.min(RADIUS, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
};

/** Stacked columns per period; each column is its own hover and focus target. */
export const StackedColumns = ({ series, labels, axisLabels, format, ariaLabel, height = 200 }: StackedColumnsProps) => {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const n = labels.length;
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = height - PAD.top - PAD.bottom;
  const totals = labels.map((_, i) => series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0));
  const ticks = niceTicks(Math.max(0, ...totals), 4, true);
  const yMax = ticks[ticks.length - 1] || 1;
  const band = n ? plotW / n : 0;
  const barW = Math.max(2, Math.min(24, band * 0.7));
  const scale = (v: number) => (v / yMax) * plotH;

  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowRight') setActive((i) => Math.min(n - 1, (i ?? -1) + 1));
    else if (event.key === 'ArrowLeft') setActive((i) => Math.max(0, (i ?? n) - 1));
    else if (event.key === 'Escape') setActive(null);
    else return;
    event.preventDefault();
  };

  return (
    <div ref={ref} className="relative outline-none focus-visible:ring-1 focus-visible:ring-accent/60 rounded-lg" tabIndex={0} onKeyDown={onKey} onBlur={() => setActive(null)} aria-label={`${ariaLabel}. Use the arrow keys to read the values.`}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} className="block">
          {ticks.map((t) => {
            const ty = PAD.top + plotH - scale(t);
            return (
              <g key={t}>
                <line x1={PAD.left} x2={PAD.left + plotW} y1={ty} y2={ty} stroke={t === 0 ? BASELINE : GRID} strokeWidth={1} />
                <text x={PAD.left - 8} y={ty} dy="0.32em" textAnchor="end" fontSize={10} fill={AXIS_TEXT} className="tabular-nums">
                  {format(t)}
                </text>
              </g>
            );
          })}
          {labelIndexes(n, Math.max(2, Math.floor(plotW / 70))).map((i) => {
            // The outer labels align with the plot's edges so they never run off the card.
            const edge = n > 1 && i === 0 ? 'start' : n > 1 && i === n - 1 ? 'end' : 'middle';
            const at = edge === 'start' ? PAD.left + band * i : edge === 'end' ? PAD.left + band * (i + 1) : PAD.left + band * (i + 0.5);
            return (
              <text key={i} x={at} y={height - 6} textAnchor={edge} fontSize={10} fill={AXIS_TEXT}>
                {axisLabels[i]}
              </text>
            );
          })}
          {labels.map((_, i) => {
            const cx = PAD.left + band * (i + 0.5) - barW / 2;
            let base = PAD.top + plotH;
            const parts = series
              .map((s) => ({ s, v: s.values[i] ?? 0 }))
              .filter((p) => p.v > 0);
            return (
              <g key={i} opacity={active === null || active === i ? 1 : 0.55}>
                {parts.map((p, j) => {
                  const h = Math.max(2, scale(p.v));
                  const top = j === parts.length - 1;
                  const drawn = top ? h : Math.max(1, h - GAP);
                  const y0 = base - h + (top ? 0 : GAP);
                  base -= h;
                  return top ? (
                    <path key={p.s.key} d={topRounded(cx, base, barW, drawn)} fill={p.s.color} />
                  ) : (
                    <rect key={p.s.key} x={cx} y={y0} width={barW} height={drawn} fill={p.s.color} />
                  );
                })}
                <rect
                  x={PAD.left + band * i}
                  y={PAD.top}
                  width={band}
                  height={plotH}
                  fill="transparent"
                  onPointerEnter={() => setActive(i)}
                  onPointerLeave={() => setActive(null)}
                />
              </g>
            );
          })}
        </svg>
      )}
      {active !== null && width > 0 && (
        <ChartTooltip
          x={PAD.left + band * (active + 0.5)}
          y={PAD.top}
          width={width}
          title={labels[active]}
          rows={[...series].reverse().map((s) => ({ color: s.color, label: s.label, value: format(s.values[active] ?? 0), shape: 'square' as const }))}
          footer={`${format(totals[active])} in total`}
        />
      )}
    </div>
  );
};
