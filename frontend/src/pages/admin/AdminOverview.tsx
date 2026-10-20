import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { CheckCircle2, RefreshCw } from 'lucide-react';
import { getOverview } from '../../api/admin/overview';
import type { Overview, OverviewPeriod, SeriesPoint } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { AttentionList } from '../../components/admin/AttentionList';
import { StatTile } from '../../components/admin/StatTile';
import { ChartCard } from '../../components/admin/charts/ChartCard';
import { LineChart } from '../../components/admin/charts/LineChart';
import { StackedColumns } from '../../components/admin/charts/StackedColumns';
import { SERIES, STATUS_COLORS } from '../../components/admin/charts/palette';
import { bucketLabel, type Bucket } from '../../components/admin/charts/scale';
import { formatPercent, formatSeconds, formatTime, formatUsd, formatUsdTick } from '../../components/admin/helpers';
import { Button, Card, ErrorBox, ModelIcon, SectionLabel, Segmented, Spinner } from '../../components/ui';
import { formatCount, shortModelName } from '../../lib/format';

const PERIODS: { value: OverviewPeriod; label: string; previous: string }[] = [
  { value: '24h', label: '24 h', previous: 'vs previous 24 h' },
  { value: '7d', label: '7 days', previous: 'vs previous 7 days' },
  { value: '30d', label: '30 days', previous: 'vs previous 30 days' },
  { value: '90d', label: '90 days', previous: 'vs previous 90 days' },
  { value: 'all', label: 'All time', previous: '' },
];

// provider_usage purposes, grouped for the cost breakdown.
const COST_GROUPS: { label: string; purposes: string[] }[] = [
  { label: 'Debate turns', purposes: ['turn', 'verdict'] },
  { label: 'Verdict and moderation', purposes: ['verdict_structure', 'moderation'] },
  { label: 'Fact-checks', purposes: ['factcheck'] },
  { label: 'Scenes, sketches, highlights', purposes: ['director', 'sketch', 'image_check', 'highlights'] },
  { label: 'AI pictures', purposes: ['image'] },
  { label: 'Voices (estimated)', purposes: ['tts'] },
  { label: 'Trending topics', purposes: ['trending', 'trending_review'] },
];

const count = (n: number) => formatCount(Math.round(n));

const pointLabel = (iso: string, bucket: Bucket) => {
  const date = new Date(iso);
  if (bucket === 'hour') {
    return `${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' })}, ${bucketLabel(iso, 'hour')} UTC`;
  }
  const day = date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
  return bucket === 'week' ? `Week of ${day}` : day;
};

const Section = ({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) => (
  <section className="mt-8">
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <SectionLabel>{title}</SectionLabel>
      {aside && <div className="text-xs text-muted">{aside}</div>}
    </div>
    {children}
  </section>
);

const Charts = ({ data }: { data: Overview }) => {
  const points: SeriesPoint[] = data.series;
  const bucket = data.bucket;
  const labels = points.map((p) => pointLabel(p.t, bucket));
  const axisLabels = points.map((p) => bucketLabel(p.t, bucket));
  const hourly = bucket === 'hour';
  const users = [
    { key: 'signups', label: 'New accounts', color: SERIES[0], values: points.map((p) => p.signups) },
    ...(hourly ? [] : [{ key: 'active', label: 'Active users', color: SERIES[1], values: points.map((p) => p.active) }]),
  ];
  const debates = [
    { key: 'completed', label: 'Completed', color: STATUS_COLORS.completed, values: points.map((p) => p.completed) },
    { key: 'stopped', label: 'Stopped', color: STATUS_COLORS.stopped, values: points.map((p) => p.stopped) },
    { key: 'error', label: 'Failed', color: STATUS_COLORS.error, values: points.map((p) => p.error) },
  ];
  const money = data.money
    ? [
        { key: 'charged', label: 'Charged to users', color: SERIES[0], values: points.map((p) => p.charged) },
        { key: 'cost', label: 'Provider cost (system keys)', color: SERIES[1], values: points.map((p) => p.cost) },
      ]
    : null;
  const table = (series: { label: string; values: (number | null)[] }[], format: (v: number) => string) => ({
    rowLabels: labels,
    columns: series.map((s) => ({ label: s.label, values: s.values.map((v) => (v === null ? '—' : format(v))) })),
  });

  return (
    <div className={`grid gap-4 ${money ? 'xl:grid-cols-3' : 'lg:grid-cols-2'}`}>
      <ChartCard
        title="People"
        subtitle={hourly ? 'New accounts per hour (activity is counted per day)' : 'New accounts and active users'}
        legend={users.map((s) => ({ label: s.label, color: s.color, shape: 'line' as const }))}
        table={table(users, count)}
      >
        <LineChart series={users} labels={labels} axisLabels={axisLabels} format={count} integer ariaLabel="New accounts and active users over time" />
      </ChartCard>
      <ChartCard
        title="Debates"
        subtitle="Started debates by how they ended"
        legend={debates.map((s) => ({ label: s.label, color: s.color, shape: 'square' as const }))}
        table={table(debates, count)}
      >
        <StackedColumns series={debates} labels={labels} axisLabels={axisLabels} format={count} ariaLabel="Debates by outcome over time" />
      </ChartCard>
      {money && (
        <ChartCard
          title="Money"
          subtitle="Credits charged against what providers cost us"
          legend={money.map((s) => ({ label: s.label, color: s.color, shape: 'line' as const }))}
          table={table(money, formatUsd)}
        >
          <LineChart series={money} labels={labels} axisLabels={axisLabels} format={formatUsd} axisFormat={formatUsdTick} ariaLabel="Charged credits and provider cost over time" />
        </ChartCard>
      )}
    </div>
  );
};

const CostBreakdown = ({ byPurpose, total, userKeys }: { byPurpose: Record<string, number>; total: number; userKeys: number }) => {
  const rows = COST_GROUPS.map((g) => ({ label: g.label, value: g.purposes.reduce((sum, p) => sum + (byPurpose[p] ?? 0), 0) })).filter((r) => r.value > 0);
  return (
    <Card padding="sm">
      <h3 className="text-sm font-semibold text-text-2">Provider cost by purpose</h3>
      <div className="mt-0.5 text-xs text-muted">System keys only; {formatUsd(userKeys)} more ran on users' own keys</div>
      {rows.length === 0 ? (
        <p className="mt-4 text-sm text-muted">Nothing spent in this period.</p>
      ) : (
        <ul className="mt-3 grid gap-2.5">
          {rows.map((row) => (
            <li key={row.label}>
              <div className="flex justify-between gap-3 text-xs">
                <span className="text-text-3">{row.label}</span>
                <span className="font-semibold tabular-nums text-text">{formatUsd(row.value)}</span>
              </div>
              <div className="mt-1 h-1 rounded-full bg-surface-3">
                <div className="h-1 rounded-full" style={{ width: `${Math.max(2, (row.value / (total || 1)) * 100)}%`, background: SERIES[0] }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
};

const TableCard = ({ title, subtitle, head, rows, empty }: { title: string; subtitle?: string; head: string[]; rows: ReactNode[][]; empty: string }) => (
  <Card padding="sm" className="min-w-0">
    <h3 className="text-sm font-semibold text-text-2">{title}</h3>
    {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
    {rows.length === 0 ? (
      <p className="mt-4 text-sm text-muted">{empty}</p>
    ) : (
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted">
            <tr>
              {head.map((h, i) => (
                <th key={h} className={`pb-2 font-medium ${i === 0 ? '' : 'whitespace-nowrap pl-3 text-right'}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((cells, r) => (
              <tr key={r} className="border-t border-line">
                {cells.map((cell, i) => (
                  <td key={i} className={`py-2 ${i === 0 ? 'pr-3 text-text-2' : 'pl-3 text-right text-text-3 whitespace-nowrap'}`}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </Card>
);

const AdminOverview = () => {
  const { me } = useAdminAuth();
  const [period, setPeriod] = useState<OverviewPeriod>('7d');
  const [refreshes, setRefreshes] = useState(0);
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getOverview(period, refreshes > 0)
      .then((overview) => {
        if (!cancelled) {
          setData(overview);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [period, refreshes]);

  const choose = (value: OverviewPeriod) => {
    setLoading(true);
    setPeriod(value);
  };
  const refresh = () => {
    setLoading(true);
    setRefreshes((n) => n + 1);
  };

  if (!me) return null;
  const previous = PERIODS.find((p) => p.value === period)?.previous ?? '';
  const u = data?.users;
  const d = data?.debates;
  const m = data?.money;
  const costsPartial = m && data && (!m.cost_tracked_since || new Date(data.start) < new Date(m.cost_tracked_since));

  return (
    <Page>
      <PageTitle kicker="Admin console" title="Overview" />

      {/* One filter row scopes everything below it. */}
      <div className="sticky top-0 z-10 -mx-1 mt-6 flex flex-wrap items-center gap-3 bg-ink/85 px-1 py-2 backdrop-blur">
        <Segmented options={PERIODS.map((p) => ({ value: p.value, label: p.label }))} value={period} onChange={choose} size="sm" />
        <Button variant="ghost" size="sm" onClick={refresh} disabled={loading} icon={loading ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />}>
          Refresh
        </Button>
        {data && <span className="text-xs text-muted">Updated {formatTime(data.generated_at)} · UTC buckets</span>}
      </div>

      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!data && !error && <Spinner className="mt-10 size-6" />}

      {data && u && d && (
        // Refetching keeps the previous numbers on screen, dimmed.
        <div className={`transition-opacity ${loading ? 'opacity-60' : ''}`}>
          <Section title="Needs attention">
            {data.attention.length ? (
              <Card padding="none" className="p-1.5">
                <AttentionList items={data.attention} />
              </Card>
            ) : (
              <Card padding="sm" className="flex items-center gap-2 text-sm text-text-3">
                <CheckCircle2 className="size-4 text-ok" /> Nothing needs a look right now.
              </Card>
            )}
          </Section>

          <Section title="People">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
              <StatTile label="New accounts" value={count(u.new.value)} current={u.new.value} previous={u.new.previous} previousLabel={previous} />
              <StatTile label="Active in the period" value={count(u.active.value)} current={u.active.value} previous={u.active.previous} previousLabel={previous} />
              <StatTile label="Active today" value={count(u.dau)} hint="UTC day" />
              <StatTile label="Active in 30 days" value={count(u.mau)} hint={`${count(u.wau)} in 7 days`} />
              <StatTile label="Accounts" value={count(u.total)} hint="all time" />
            </div>
          </Section>

          <Section title="Debates" aside={d.running_now ? `${d.running_now} running now` : undefined}>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <StatTile label="Started" value={count(d.started.value)} current={d.started.value} previous={d.started.previous} previousLabel={previous} />
              <StatTile label="Completed" value={count(d.completed.value)} current={d.completed.value} previous={d.completed.previous} previousLabel={previous} />
              <StatTile
                label="Failed"
                value={count(d.failed.value)}
                current={d.failed.value}
                previous={d.failed.previous}
                upIsGood={false}
                previousLabel={previous}
                hint={`${formatPercent(d.error_rate.value)} of finished`}
              />
              <StatTile label="Audio built" value={count(d.media_ready.value)} current={d.media_ready.value} previous={d.media_ready.previous} previousLabel={previous} hint={d.media_failed.value ? `${count(d.media_failed.value)} failed` : undefined} />
              <StatTile label="Published" value={count(d.published.value)} current={d.published.value} previous={d.published.previous} previousLabel={previous} />
              <StatTile label="Likes · votes" value={`${count(d.likes.value)} · ${count(d.votes.value)}`} hint={`${count(d.renders)} MP4 exports`} />
            </div>
          </Section>

          {m && (
            <Section
              title="Money"
              aside={
                costsPartial
                  ? m.cost_tracked_since
                    ? `≈ provider costs are tracked since ${formatTime(m.cost_tracked_since)}`
                    : '≈ no provider costs recorded yet'
                  : undefined
              }
            >
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
                <StatTile label="Top-ups" value={formatUsd(m.topups)} current={m.topups} previous={m.topups_previous} previousLabel={previous} format={formatUsd} hint={m.bonuses || m.refunds ? `+${formatUsd(m.bonuses + m.refunds)} bonuses and refunds` : undefined} />
                <StatTile
                  label="Charged to users"
                  value={formatUsd(m.charged_total)}
                  current={m.charged_total}
                  previous={m.charged_total_previous}
                  previousLabel={previous}
                  format={formatUsd}
                  hint={`models ${formatUsd(m.charged.models)} · voices ${formatUsd(m.charged.voices)} · pictures ${formatUsd(m.charged.pictures)}`}
                />
                <StatTile label="Provider cost" value={formatUsd(m.cost_system)} current={m.cost_system} previous={m.cost_system_previous} upIsGood={false} previousLabel={previous} format={formatUsd} hint="system keys" />
                <StatTile label="Margin" value={formatUsd(m.margin)} current={m.margin} previous={m.margin_previous} previousLabel={previous} format={formatUsd} hint="charged − provider cost" />
                <StatTile
                  label="Credits held by users"
                  value={formatUsd(m.liabilities)}
                  hint={m.negative_balances ? `${m.negative_balances} below zero (${formatUsd(m.negative_total)})` : 'what we owe in service'}
                />
              </div>
            </Section>
          )}

          <Section title="Over time">
            <Charts data={data} />
          </Section>

          <Section title="This period's leaders">
            <div className="grid items-start gap-4 xl:grid-cols-2">
              <TableCard
                title="Models"
                subtitle="Debaters by number of debates; tries include retries"
                head={['Model', 'Debates', 'Tries', 'Failed', 'First word', 'Cost']}
                empty="No debates in this period."
                rows={data.top_models.map((row) => [
                  <span key="m" className="flex max-w-56 min-w-0 items-center gap-2">
                    <ModelIcon modelId={row.model} size={14} />
                    <span className="truncate" title={row.model}>
                      {shortModelName(row.model)}
                    </span>
                  </span>,
                  count(row.debates),
                  count(row.turns),
                  formatPercent(row.failure_rate),
                  formatSeconds(row.avg_ttft_ms),
                  formatUsd(row.cost),
                ])}
              />
              <div className="grid gap-4">
                {m && <CostBreakdown byPurpose={m.cost_by_purpose} total={m.cost_system} userKeys={m.cost_user_keys} />}
                {data.top_spenders && (
                  <TableCard
                    title="Top spenders"
                    head={['Account', 'Spent']}
                    empty="Nobody was charged in this period."
                    rows={data.top_spenders.map((row) => [
                      <Link key="u" to={`/admin/users/${row.user_id}`} className="block max-w-72 truncate hover:text-text" title={row.email}>
                        {row.display_name} <span className="text-muted">{row.email}</span>
                      </Link>,
                      formatUsd(row.spent),
                    ])}
                  />
                )}
              </div>
              <TableCard
                title="Debates people liked"
                head={['Debate', 'Likes', 'Views', 'Votes']}
                empty="No debates in this period."
                rows={data.top_debates.map((row) => [
                  row.url ? (
                    <a key="d" href={row.url} target="_blank" rel="noreferrer" className="block max-w-72 truncate hover:text-text" title={row.title}>
                      {row.title}
                    </a>
                  ) : (
                    <span key="d" className="block max-w-72 truncate" title={`${row.title} (private)`}>
                      {row.title} <span className="text-muted">· private</span>
                    </span>
                  ),
                  count(row.likes),
                  count(row.views),
                  count(row.votes),
                ])}
              />
            </div>
          </Section>

          <p className="mt-8 text-xs text-muted">
            Debates and system pages arrive next. Your session and recovery codes: <Link to="/admin/security" className="text-accent hover:text-accent-hover">Security</Link>.
          </p>
        </div>
      )}
    </Page>
  );
};

export default AdminOverview;
