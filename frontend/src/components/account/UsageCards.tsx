import type { Usage, UsageDay } from '../../api/types';
import { formatTokens } from '../../lib/format';
import { SectionLabel } from '../ui';

interface Metric {
  label: string;
  color: string;
  total: (u: Usage) => number;
  daily: (d: UsageDay) => number;
  format: (n: number) => string;
  empty: string;
}

const minutes = (ms: number) => {
  const m = ms / 60_000;
  return m > 0 && m < 1 ? '<1 min' : `${Math.round(m)} min`;
};

const METRICS: Metric[] = [
  {
    label: 'Model tokens',
    color: '#6C9CFF',
    total: (u) => u.tokens_in + u.tokens_out,
    daily: (d) => d.tokens,
    format: formatTokens,
    empty: 'No debates this month',
  },
  {
    label: 'Voice minutes',
    color: '#FFC46B',
    total: (u) => u.voice_ms,
    daily: (d) => d.voice_ms,
    format: minutes,
    empty: 'No voiced debates yet',
  },
  {
    label: 'Renders',
    color: '#D9FF3D',
    total: (u) => u.renders,
    daily: (d) => d.renders,
    format: String,
    empty: 'No videos rendered yet',
  },
];

// Usage buckets are UTC calendar days: show them as such, whatever the visitor's time zone.
/** "Oct 14" for a "2026-10-14" bucket. */
const dayLabel = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
/** "Oct 1, 2026" for the period start. */
const periodLabel = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });

const UsageTile = ({ metric, usage }: { metric: Metric; usage: Usage | null }) => {
  const days = usage?.days ?? [];
  const values = days.map(metric.daily);
  const peak = Math.max(0, ...values);
  const total = usage ? metric.total(usage) : null;
  return (
    <div className="rounded-panel border border-line bg-surface px-5 py-[18px]">
      <div className="flex items-center justify-between">
        <span className="text-[13px] text-text-3">{metric.label}</span>
        <span className="size-2 rounded-full" style={{ background: metric.color }} />
      </div>
      <div className="mt-2 font-display text-[30px] font-bold tracking-[-0.03em]">{total === null ? '—' : metric.format(total)}</div>
      <div className="mt-3 flex h-7 items-end gap-[3px]" aria-hidden="true">
        {(values.length > 0 ? values : Array.from({ length: 14 }, () => 0)).map((v, i) => (
          <div
            key={days[i]?.date ?? i}
            title={days[i] ? `${dayLabel(days[i].date)}: ${metric.format(v)}` : undefined}
            className="min-w-0 flex-1 rounded-[2px]"
            style={{ height: `${v > 0 && peak > 0 ? Math.max(6, (v / peak) * 100) : 6}%`, background: v > 0 ? metric.color : 'var(--color-surface-3)' }}
          />
        ))}
      </div>
      <div className="mt-1.5 text-[11px] text-dim">
        {!usage ? 'Loading…' : total ? `Daily, last ${days.length} ${days.length === 1 ? 'day' : 'days'}` : metric.empty}
      </div>
    </div>
  );
};

/** THIS MONTH: tokens, voice time and renders with a bar per day. */
export const UsageCards = ({ usage, error }: { usage: Usage | null; error: string | null }) => (
  <div>
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <SectionLabel>This month</SectionLabel>
      {usage && <span className="font-mono text-[11px] text-dim">since {periodLabel(usage.period_start)}</span>}
    </div>
    {error ? (
      <div className="rounded-panel border border-line bg-surface px-5 py-4 text-xs text-con">{error}</div>
    ) : (
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,220px),1fr))] gap-3">
        {METRICS.map((m) => (
          <UsageTile key={m.label} metric={m} usage={usage} />
        ))}
      </div>
    )}
  </div>
);
