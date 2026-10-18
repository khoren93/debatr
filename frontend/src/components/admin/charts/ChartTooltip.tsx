import type { ReactNode } from 'react';

export interface TooltipRow {
  color: string;
  label: string;
  value: string;
  /** Lines get a short stroke key, bars a square. */
  shape?: 'line' | 'square';
}

interface ChartTooltipProps {
  x: number;
  y: number;
  width: number;
  title: ReactNode;
  rows: TooltipRow[];
  footer?: ReactNode;
}

/** One readout for every series at the hovered position; values lead, labels follow. */
export const ChartTooltip = ({ x, y, width, title, rows, footer }: ChartTooltipProps) => {
  const flip = x > width - 180;
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 min-w-36 rounded-[10px] border border-line-2 bg-ink/95 px-3 py-2 shadow-xl backdrop-blur"
      style={{ left: flip ? undefined : x + 14, right: flip ? width - x + 14 : undefined, top: Math.max(0, y - 8) }}
    >
      <div className="text-[11px] text-muted">{title}</div>
      <ul className="mt-1 grid gap-1">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-2 whitespace-nowrap text-xs">
            <span
              aria-hidden
              className={row.shape === 'square' ? 'size-2.5 rounded-[3px]' : 'h-0.5 w-3 rounded-full'}
              style={{ background: row.color }}
            />
            <span className="font-semibold tabular-nums text-text">{row.value}</span>
            <span className="text-muted">{row.label}</span>
          </li>
        ))}
      </ul>
      {footer && <div className="mt-1.5 border-t border-line pt-1.5 text-xs text-text-3">{footer}</div>}
    </div>
  );
};
