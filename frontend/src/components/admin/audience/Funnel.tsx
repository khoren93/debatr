import type { FunnelStep } from '../../../api/admin/types';
import { formatCount } from '../../../lib/format';
import { Card } from '../../ui';
import { SERIES } from '../charts/palette';
import { formatPercent } from '../helpers';

/** Visitors who got to each step (each step on its own: not a strict sequence). */
export const Funnel = ({ steps }: { steps: FunnelStep[] }) => {
  const first = steps[0]?.visitors ?? 0;
  return (
    <Card padding="sm" className="min-w-0">
      <h3 className="text-sm font-semibold text-text-2">From visit to customer</h3>
      <div className="mt-0.5 text-xs text-muted">Visitors of the period who did each, with the share of all visitors</div>
      <ul className="mt-3 grid gap-2.5">
        {steps.map((step) => {
          const share = first ? step.visitors / first : 0;
          return (
            <li key={step.key} title={`${step.visitors} visitors · ${formatPercent(share)}`}>
              <div className="flex justify-between gap-3 text-xs">
                <span className="text-text-3">{step.label}</span>
                <span className="tabular-nums">
                  <span className="font-semibold text-text">{formatCount(step.visitors)}</span>
                  <span className="ml-2 text-muted">{formatPercent(share)}</span>
                </span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-surface-3">
                <div className="h-1.5 rounded-full" style={{ width: `${step.visitors ? Math.max(1.5, share * 100) : 0}%`, background: SERIES[0] }} />
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
};
