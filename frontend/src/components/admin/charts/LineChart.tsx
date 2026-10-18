import { useState, type KeyboardEvent, type PointerEvent } from 'react';
import { AXIS_TEXT, BASELINE, GRID, SURFACE } from './palette';
import { labelIndexes, niceTicks } from './scale';
import { ChartTooltip } from './ChartTooltip';
import { useWidth } from './useWidth';

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
}

interface LineChartProps {
  series: LineSeries[];
  /** Full label of each point (tooltip) and its short axis label. */
  labels: string[];
  axisLabels: string[];
  format: (value: number) => string;
  axisFormat?: (value: number) => string;
  /** Whole-number axis steps (counts). */
  integer?: boolean;
  ariaLabel: string;
  height?: number;
}

const PAD = { left: 44, right: 52, top: 10, bottom: 24 };

/** Lines over time on one axis, with a crosshair readout of every series. */
export const LineChart = ({ series, labels, axisLabels, format, axisFormat = format, integer = false, ariaLabel, height = 200 }: LineChartProps) => {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const n = labels.length;
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = height - PAD.top - PAD.bottom;
  const max = Math.max(0, ...series.flatMap((s) => s.values.filter((v): v is number => v !== null)));
  const ticks = niceTicks(max, 4, integer);
  const yMax = ticks[ticks.length - 1] || 1;
  const x = (i: number) => PAD.left + (n <= 1 ? plotW / 2 : (i * plotW) / (n - 1));
  const y = (v: number) => PAD.top + plotH - (v / yMax) * plotH;

  const path = (values: (number | null)[]) => {
    let d = '';
    let pen = false;
    values.forEach((v, i) => {
      if (v === null) {
        pen = false;
        return;
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  // End labels only while they stay apart; otherwise the legend and the readout carry them.
  const ends = series
    .map((s) => {
      const last = s.values.reduce<number>((found, v, i) => (v !== null ? i : found), -1);
      return last < 0 ? null : { key: s.key, index: last, value: s.values[last] as number };
    })
    .filter((e): e is { key: string; index: number; value: number } => e !== null);
  const endsApart = ends.every((a, i) => ends.every((b, j) => i === j || Math.abs(y(a.value) - y(b.value)) >= 14));

  const pick = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - box.left;
    setActive(n <= 1 ? 0 : Math.min(n - 1, Math.max(0, Math.round((px / box.width) * (n - 1)))));
  };
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
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={PAD.left + plotW} y1={y(t)} y2={y(t)} stroke={t === 0 ? BASELINE : GRID} strokeWidth={1} />
              <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={10} fill={AXIS_TEXT} className="tabular-nums">
                {axisFormat(t)}
              </text>
            </g>
          ))}
          {labelIndexes(n, Math.max(2, Math.floor(plotW / 70))).map((i) => (
            <text key={i} x={x(i)} y={height - 6} textAnchor={n > 1 && i === n - 1 ? 'end' : n > 1 && i === 0 ? 'start' : 'middle'} fontSize={10} fill={AXIS_TEXT}>
              {axisLabels[i]}
            </text>
          ))}
          {series.map((s) => (
            <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {n === 1 &&
            series.map((s) =>
              s.values[0] === null ? null : <circle key={s.key} cx={x(0)} cy={y(s.values[0])} r={4} fill={s.color} stroke={SURFACE} strokeWidth={2} />,
            )}
          {endsApart &&
            ends.map((e) => (
              <text key={e.key} x={x(e.index) + 8} y={y(e.value)} dy="0.32em" fontSize={11} fill="#d5d8e2" className="tabular-nums">
                {format(e.value)}
              </text>
            ))}
          {active !== null && (
            <g>
              <line x1={x(active)} x2={x(active)} y1={PAD.top} y2={PAD.top + plotH} stroke={BASELINE} strokeWidth={1} />
              {series.map((s) => {
                const v = s.values[active];
                return v === null ? null : <circle key={s.key} cx={x(active)} cy={y(v)} r={4} fill={s.color} stroke={SURFACE} strokeWidth={2} />;
              })}
            </g>
          )}
          <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} fill="transparent" onPointerMove={pick} onPointerLeave={() => setActive(null)} />
        </svg>
      )}
      {active !== null && width > 0 && (
        <ChartTooltip
          x={x(active)}
          y={PAD.top}
          width={width}
          title={labels[active]}
          rows={series.map((s) => ({
            color: s.color,
            label: s.label,
            value: s.values[active] === null ? '—' : format(s.values[active] as number),
          }))}
        />
      )}
    </div>
  );
};
