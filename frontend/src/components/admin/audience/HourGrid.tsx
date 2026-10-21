import { useState } from 'react';
import { ChartCard } from '../charts/ChartCard';
import { ChartTooltip } from '../charts/ChartTooltip';
import { HEAT_STEPS, HEAT_EMPTY } from '../charts/palette';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const hourLabel = (h: number) => `${String(h).padStart(2, '0')}:00`;

/** A cell's colour: one blue ramp, dark (few) to light (many); none is the neutral surface. */
const heatColor = (value: number, max: number) => {
  if (value <= 0 || max <= 0) return HEAT_EMPTY;
  const step = Math.min(HEAT_STEPS.length - 1, Math.ceil((value / max) * HEAT_STEPS.length) - 1);
  return HEAT_STEPS[Math.max(0, step)];
};

/** When visits start: weekday × hour in the chosen time zone, with a per-cell tooltip. */
export const HourGrid = ({ hours, timezone }: { hours: number[][]; timezone: string }) => {
  const [hover, setHover] = useState<{ day: number; hour: number; x: number; y: number; width: number } | null>(null);
  const max = Math.max(0, ...hours.flat());
  const total = hours.flat().reduce((a, b) => a + b, 0);
  return (
    <ChartCard
      title="When visits start"
      subtitle={`Weekday by hour, ${timezone.replace('_', ' ')}`}
      table={{ rowLabels: DAYS, columns: Array.from({ length: 24 }, (_, h) => ({ label: hourLabel(h), values: hours.map((row) => String(row[h] ?? 0)) })) }}
    >
      {total === 0 ? (
        <p className="py-6 text-sm text-muted">No visits in this period.</p>
      ) : (
        <div className="relative" onMouseLeave={() => setHover(null)}>
          <div className="grid grid-cols-[32px_repeat(24,minmax(0,1fr))] gap-[2px]">
            <span />
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="text-center text-[9px] text-muted tabular-nums">
                {h % 3 === 0 ? h : ''}
              </span>
            ))}
            {hours.map((row, d) => [
              <span key={`d${d}`} className="self-center text-[10px] text-muted">
                {DAYS[d]}
              </span>,
              ...row.map((value, h) => (
                <span
                  key={`${d}-${h}`}
                  className={`aspect-square min-h-3 rounded-[3px] ${hover?.day === d && hover.hour === h ? 'outline-2 outline-offset-1 outline-text-2' : ''}`}
                  style={{ background: heatColor(value, max) }}
                  onMouseEnter={(e) => {
                    const box = e.currentTarget.parentElement?.getBoundingClientRect();
                    const cell = e.currentTarget.getBoundingClientRect();
                    if (box) setHover({ day: d, hour: h, x: cell.left - box.left + cell.width / 2, y: cell.top - box.top, width: box.width });
                  }}
                />
              )),
            ])}
          </div>
          {hover && (
            <ChartTooltip
              x={hover.x}
              y={hover.y}
              width={hover.width}
              title={`${DAYS[hover.day]} ${hourLabel(hover.hour)}–${hourLabel((hover.hour + 1) % 24)}`}
              rows={[{ color: heatColor(hours[hover.day][hover.hour], max), label: 'visits started', value: String(hours[hover.day][hover.hour]), shape: 'square' }]}
            />
          )}
          <div className="mt-3 flex items-center gap-2 text-[10px] text-muted">
            <span>fewer</span>
            <span className="flex gap-[2px]">
              {HEAT_STEPS.map((c) => (
                <span key={c} className="h-2 w-4 rounded-[2px]" style={{ background: c }} />
              ))}
            </span>
            <span>more · busiest hour {max}</span>
          </div>
        </div>
      )}
    </ChartCard>
  );
};
