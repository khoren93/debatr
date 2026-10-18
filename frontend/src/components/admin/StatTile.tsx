import type { ReactNode } from 'react';
import { ArrowDownRight, ArrowUpRight } from 'lucide-react';

interface StatTileProps {
  label: string;
  value: string;
  /** Raw numbers for the change against the period before. */
  current?: number;
  previous?: number | null;
  /** Whether a rise is good news (failures and costs: false). */
  upIsGood?: boolean;
  format?: (delta: number) => string;
  previousLabel?: string;
  hint?: ReactNode;
}

/** A KPI: label, value and the change against the previous period. */
export const StatTile = ({ label, value, current, previous, upIsGood = true, format = (d) => `${d}`, previousLabel, hint }: StatTileProps) => {
  const delta = current !== undefined && previous !== null && previous !== undefined ? current - previous : null;
  const good = delta !== null && delta !== 0 && delta > 0 === upIsGood;
  const percent = delta !== null && previous ? Math.round((delta / Math.abs(previous)) * 100) : null;
  return (
    <div className="rounded-[14px] border border-line bg-surface p-3.5">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 font-display text-2xl font-bold tracking-tight">{value}</div>
      {delta !== null ? (
        <div className="mt-1 flex items-center gap-1 text-[11px]">
          {delta === 0 ? (
            <span className="text-muted">no change {previousLabel}</span>
          ) : (
            <>
              <span className={`flex items-center font-semibold ${good ? 'text-ok' : 'text-con'}`}>
                {delta > 0 ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
                {delta > 0 ? '+' : '−'}
                {format(Math.abs(delta))}
                {percent !== null && ` (${percent > 0 ? '+' : ''}${percent}%)`}
              </span>
              <span className="text-muted">{previousLabel}</span>
            </>
          )}
        </div>
      ) : (
        hint && <div className="mt-1 text-[11px] text-muted">{hint}</div>
      )}
      {delta !== null && hint && <div className="mt-0.5 text-[11px] text-muted">{hint}</div>}
    </div>
  );
};
