import type { ReactNode } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, ErrorBox, SectionLabel, Spinner } from '../../ui';

/** A titled part of the System page with its own refresh and error. */
export const SystemSection = ({
  id,
  title,
  aside,
  loading,
  error,
  onRefresh,
  children,
}: {
  id: string;
  title: string;
  aside?: ReactNode;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  children: ReactNode;
}) => (
  <section id={id} className="scroll-mt-20 pt-8">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-3">
        <SectionLabel>{title}</SectionLabel>
        {aside && <span className="text-xs text-muted">{aside}</span>}
      </div>
      <Button variant="ghost" size="sm" onClick={onRefresh} disabled={loading} icon={loading ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />}>
        Refresh
      </Button>
    </div>
    {error && <ErrorBox className="mb-3">{error}</ErrorBox>}
    <div className={`transition-opacity ${loading ? 'opacity-70' : ''}`}>{children}</div>
  </section>
);

/** A small number with its label (queues, limits, health). */
export const Figure = ({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'ok' | 'warn' | 'bad' }) => {
  const color = tone === 'bad' ? 'text-con' : tone === 'warn' ? 'text-host' : tone === 'ok' ? 'text-ok' : '';
  return (
    <div className="rounded-[14px] border border-line bg-surface p-3.5">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 font-display text-xl font-bold tracking-tight ${color}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted">{hint}</div>}
    </div>
  );
};

/** A coloured state dot with its text (green = good, amber = attention, red = bad). */
export const State = ({ tone, children }: { tone: 'ok' | 'warn' | 'bad' | 'off'; children: ReactNode }) => {
  const dot = { ok: 'bg-ok', warn: 'bg-host', bad: 'bg-con', off: 'bg-surface-4' }[tone];
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block size-2 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      {children}
    </span>
  );
};

export const Rows = ({ rows }: { rows: [string, ReactNode][] }) => (
  <div className="divide-y divide-line/70 px-4 py-1.5">
    {rows.map(([label, value]) => (
      <div key={label} className="flex items-baseline justify-between gap-4 py-1.5 text-xs">
        <span className="shrink-0 text-muted">{label}</span>
        <span className="min-w-0 text-right text-text-2 [overflow-wrap:anywhere]">{value}</span>
      </div>
    ))}
  </div>
);
