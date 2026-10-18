import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getModels } from '../../api/admin/finance';
import type { ModelRow, ModelsPeriod } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { DataTable, type Column, type SortState } from '../../components/admin/DataTable';
import { formatPercent, formatSeconds, formatUsd } from '../../components/admin/helpers';
import { Card, ErrorBox, ModelIcon, Segmented, Spinner } from '../../components/ui';

const PERIODS: { value: ModelsPeriod; label: string }[] = [
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: 'all', label: 'All time' },
];

const ratio = (wins: number, of: number) => (of ? wins / of : null);

// Client-side sort keys: a number per row (null sorts last).
const SORTS: Record<string, (r: ModelRow) => number | null> = {
  tries: (r) => r.tries,
  debates: (r) => r.debates,
  failures: (r) => r.failure_rate,
  duration: (r) => r.duration_p50_ms,
  ttft: (r) => r.ttft_p50_ms,
  cost: (r) => r.cost_per_turn,
  judge: (r) => ratio(r.judge_wins, r.judge_contests),
  audience: (r) => ratio(r.audience_wins, r.audience_contests),
  accuracy: (r) => ratio(r.claims_verified, r.claims_checked),
  pins: (r) => r.router_pins,
};

const sorted = (rows: ModelRow[], sort: SortState) => {
  const value = SORTS[sort.key] ?? SORTS.tries;
  const sign = sort.order === 'desc' ? -1 : 1;
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    if (x === null && y === null) return a.model.localeCompare(b.model);
    if (x === null) return 1;
    if (y === null) return -1;
    return (x - y) * sign || a.model.localeCompare(b.model);
  });
};

const pair = (p50: number | null, p90: number | null) => (p50 === null ? '—' : `${formatSeconds(p50)} · ${formatSeconds(p90)}`);

const winRate = (wins: number, of: number) => (of ? `${wins}/${of} (${formatPercent(wins / of)})` : <span className="text-dim">—</span>);

const columns = (withMoney: boolean): Column<ModelRow>[] => [
  {
    key: 'model',
    header: 'Model',
    cell: (r) => (
      <span className="flex min-w-0 max-w-[280px] 2xl:max-w-[420px] items-center gap-2">
        <ModelIcon modelId={r.model} size={16} />
        <span className="flex min-w-0 flex-col">
          <Link to={`/admin/debates?model=${encodeURIComponent(r.model)}`} className="truncate font-semibold text-text-2 hover:underline" title={r.model}>
            {r.name}
          </Link>
          <span className="truncate font-mono text-[11px] text-muted">
            {r.model}
            {r.is_free && <span className="text-ok"> · free</span>}
            {!r.in_catalogue && <span className="text-con"> · gone from OpenRouter</span>}
          </span>
        </span>
      </span>
    ),
  },
  { key: 'debates', header: 'Debates', sort: 'debates', align: 'right', cell: (r) => r.debates },
  {
    key: 'tries',
    header: 'Tries',
    sort: 'tries',
    align: 'right',
    cell: (r) => <span title={r.own_key_tries ? `${r.own_key_tries} on users' own keys` : undefined}>{r.tries}</span>,
  },
  {
    key: 'failures',
    header: 'Failed',
    sort: 'failures',
    align: 'right',
    cell: (r) => {
      const kinds = Object.entries(r.errors)
        .map(([kind, n]) => `${kind} ${n}`)
        .join(' · ');
      const bad = (r.failure_rate ?? 0) >= 0.1;
      return (
        <span className={bad ? 'font-semibold text-con' : ''} title={kinds || undefined}>
          {formatPercent(r.failure_rate)}
        </span>
      );
    },
  },
  { key: 'duration', header: 'Turn p50 · p90', sort: 'duration', align: 'right', className: 'whitespace-nowrap text-text-3', cell: (r) => pair(r.duration_p50_ms, r.duration_p90_ms) },
  { key: 'ttft', header: 'First word p50 · p90', sort: 'ttft', align: 'right', className: 'whitespace-nowrap text-text-3', cell: (r) => pair(r.ttft_p50_ms, r.ttft_p90_ms) },
  ...(withMoney ? [{ key: 'cost', header: 'Per turn', sort: 'cost', align: 'right' as const, cell: (r: ModelRow) => (r.cost_per_turn === null ? '—' : formatUsd(r.cost_per_turn)) }] : []),
  { key: 'judge', header: 'Judge wins', sort: 'judge', align: 'right', className: 'whitespace-nowrap', cell: (r) => winRate(r.judge_wins, r.judge_contests) },
  { key: 'audience', header: 'Audience wins', sort: 'audience', align: 'right', className: 'whitespace-nowrap', cell: (r) => winRate(r.audience_wins, r.audience_contests) },
  {
    key: 'accuracy',
    header: 'Fact-checks',
    sort: 'accuracy',
    align: 'right',
    className: 'whitespace-nowrap',
    cell: (r) =>
      r.claims_checked ? (
        <span title={`${r.claims_disputed} disputed`}>
          {r.claims_verified}/{r.claims_checked} verified
        </span>
      ) : (
        <span className="text-dim">—</span>
      ),
  },
  { key: 'pins', header: 'Router picks', sort: 'pins', align: 'right', className: 'text-text-3', cell: (r) => (r.router_pins ? r.router_pins : '—') },
];

const AdminModels = () => {
  const { me } = useAdminAuth();
  const [period, setPeriod] = useState<ModelsPeriod>('30d');
  const [sort, setSort] = useState<SortState>({ key: 'tries', order: 'desc' });
  const [result, setResult] = useState<{ period: ModelsPeriod; rows: ModelRow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getModels(period)
      .then((rows) => {
        if (!cancelled) {
          setResult({ period, rows });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [period]);

  const withMoney = Boolean(me?.permissions.includes('money'));
  const onSort = (key: string) => setSort((current) => ({ key, order: current.key === key && current.order === 'desc' ? 'asc' : 'desc' }));

  return (
    <Page>
      <PageTitle kicker="Admin console" title="Models" />
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Segmented options={PERIODS} value={period} onChange={setPeriod} size="sm" />
        <span className="text-xs text-muted">Tries are turn and verdict calls, retries included; wins count finished debates against another model.</span>
      </div>
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!result && !error && <Spinner className="mt-10 size-6" />}
      {result && (
        <Card padding="none" className="mt-4 overflow-hidden">
          <DataTable
            caption="Models"
            columns={columns(withMoney)}
            rows={sorted(result.rows, sort)}
            rowKey={(r) => r.model}
            sort={sort}
            onSort={onSort}
            loading={result.period !== period}
            empty="No model answered in this period."
          />
        </Card>
      )}
    </Page>
  );
};

export default AdminModels;
