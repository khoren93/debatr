import type { ReactNode } from 'react';
import { formatCount } from '../../../lib/format';
import { Card } from '../../ui';
import { SERIES } from '../charts/palette';
import { formatPercent } from '../helpers';

export interface ShareItem {
  key: string;
  label: ReactNode;
  value: number;
  /** A second number after the share (time, bounce). */
  extra?: string;
}

/** A breakdown as labelled bars: count and share of the total on each row. */
export const ShareList = ({ title, subtitle, items, empty = 'Nothing in this period.', total }: { title: string; subtitle?: string; items: ShareItem[]; empty?: string; total?: number }) => {
  const sum = total ?? items.reduce((a, b) => a + b.value, 0);
  return (
    <Card padding="sm" className="min-w-0">
      <h3 className="text-sm font-semibold text-text-2">{title}</h3>
      {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted">{empty}</p>
      ) : (
        <ul className="mt-3 grid gap-2.5">
          {items.map((item) => {
            const share = sum ? item.value / sum : 0;
            return (
              <li key={item.key}>
                <div className="flex justify-between gap-3 text-xs">
                  <span className="min-w-0 truncate text-text-3">{item.label}</span>
                  <span className="shrink-0 tabular-nums">
                    <span className="font-semibold text-text">{formatCount(item.value)}</span>
                    <span className="ml-2 text-muted">{formatPercent(share)}</span>
                    {item.extra && <span className="ml-2 text-muted">{item.extra}</span>}
                  </span>
                </div>
                <div className="mt-1 h-1 rounded-full bg-surface-3">
                  <div className="h-1 rounded-full" style={{ width: `${Math.max(1.5, share * 100)}%`, background: SERIES[0] }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
};
