import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Download } from 'lucide-react';
import { needsSudo } from '../../api/admin/client';
import { exportFinance, getFinance } from '../../api/admin/finance';
import type { FinanceOut, FinancePeriod, TopAccount } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { DataTable, type Column } from '../../components/admin/DataTable';
import { StatTile } from '../../components/admin/StatTile';
import { SudoDialog } from '../../components/admin/SudoDialog';
import { ChartCard } from '../../components/admin/charts/ChartCard';
import { LineChart } from '../../components/admin/charts/LineChart';
import { StackedColumns } from '../../components/admin/charts/StackedColumns';
import { SERIES, SPEND_COLORS } from '../../components/admin/charts/palette';
import { bucketLabel } from '../../components/admin/charts/scale';
import { formatTime, formatUsd, formatUsdTick } from '../../components/admin/helpers';
import { Panel } from '../../components/admin/users/UserSections';
import { downloadBlob } from '../../components/debate/helpers';
import { Button, ErrorBox, SectionLabel, Segmented, Spinner, useToast } from '../../components/ui';

const PERIODS: { value: FinancePeriod; label: string }[] = [
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: '12m', label: '12 months' },
  { value: 'all', label: 'All time' },
];

// provider_usage purposes the owner pays for; the rest is ours alone.
const BILLED = new Set(['turn', 'verdict', 'factcheck', 'image', 'tts', 'music', 'cover', 'cover_director']);
const PURPOSES: Record<string, string> = {
  turn: 'Debate turns',
  verdict: 'Verdicts',
  factcheck: 'Fact-checks',
  image: 'AI pictures',
  tts: 'Premium voices (estimated)',
  music: 'Battle music (estimated)',
  cover: 'AI covers',
  cover_director: 'Cover art director',
  cover_check: 'Cover checks',
  director: 'Scene director',
  sketch: 'Sketches',
  image_check: 'Picture checks',
  highlights: 'Short-video highlights',
  verdict_structure: 'Verdict structuring',
  moderation: 'Gallery check',
  trending: 'Trending topics',
  trending_review: 'Trending safety review',
};

const label = (iso: string, bucket: FinanceOut['bucket'], long: boolean) => {
  const date = new Date(iso);
  if (bucket === 'month') return date.toLocaleDateString(undefined, { month: long ? 'long' : 'short', year: long ? 'numeric' : '2-digit', timeZone: 'UTC' });
  if (!long) return bucketLabel(iso, bucket);
  const day = date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
  return bucket === 'week' ? `Week of ${day}` : day;
};

const accountColumns: Column<TopAccount>[] = [
  {
    key: 'email',
    header: 'Account',
    cell: (a) => (
      <Link to={`/admin/users/${a.user_id}`} className="block max-w-[260px] 2xl:max-w-[380px] truncate text-text-2 hover:underline">
        {a.email}
      </Link>
    ),
  },
  { key: 'amount', header: 'Amount', align: 'right', cell: (a) => formatUsd(a.amount) },
];

const Charts = ({ data }: { data: FinanceOut }) => {
  const labels = data.series.map((p) => label(p.t, data.bucket, true));
  const axisLabels = data.series.map((p) => label(p.t, data.bucket, false));
  const charged = (['models', 'voices', 'pictures', 'music', 'cover'] as const).map((key) => ({
    key,
    label: { models: 'Model tokens', voices: 'Premium voices', pictures: 'AI pictures', music: 'Battle music', cover: 'AI covers' }[key],
    color: SPEND_COLORS[key],
    values: data.series.map((p) => p[`charged_${key}`]),
  }));
  const versus = [
    { key: 'charged', label: 'Charged to users', color: SERIES[0], values: data.series.map((p) => p.charged) },
    { key: 'cost', label: 'Provider cost (system keys)', color: SERIES[1], values: data.series.map((p) => p.cost) },
  ];
  const table = (series: { label: string; values: (number | null)[] }[]) => ({
    rowLabels: labels,
    columns: series.map((s) => ({ label: s.label, values: s.values.map((v) => (v === null ? '—' : formatUsd(v))) })),
  });
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ChartCard title="Charges" subtitle={`By what they paid for, per ${data.bucket} (UTC)`} legend={charged.map((s) => ({ label: s.label, color: s.color, shape: 'square' as const }))} table={table(charged)}>
        <StackedColumns series={charged} labels={labels} axisLabels={axisLabels} format={formatUsd} ariaLabel="Charges by category over time" />
      </ChartCard>
      <ChartCard title="Charged against cost" subtitle="Credits charged and what providers cost us" legend={versus.map((s) => ({ label: s.label, color: s.color, shape: 'line' as const }))} table={table(versus)}>
        <LineChart series={versus} labels={labels} axisLabels={axisLabels} format={formatUsd} axisFormat={formatUsdTick} ariaLabel="Charged credits and provider cost over time" />
      </ChartCard>
    </div>
  );
};

const AdminFinance = () => {
  const toast = useToast();
  const [period, setPeriod] = useState<FinancePeriod>('30d');
  const [result, setResult] = useState<{ period: FinancePeriod; data: FinanceOut } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [askCode, setAskCode] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getFinance(period)
      .then((data) => {
        if (!cancelled) {
          setResult({ period, data });
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

  const download = async () => {
    setExporting(true);
    try {
      const { blob, name } = await exportFinance(period);
      downloadBlob(blob, name);
    } catch (err) {
      if (needsSudo(err)) setAskCode(true);
      else toast.error(getErrorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  const data = result?.data;
  const t = data?.totals;
  const partial = data && (!data.cost_tracked_since || new Date(data.start) < new Date(data.cost_tracked_since));
  const purposes = data ? Object.entries(data.cost_by_purpose) : [];
  const stripe = data?.stripe;

  return (
    <Page>
      <PageTitle
        kicker="Admin console"
        title="Finance"
        right={
          <Button variant="secondary" size="sm" icon={<Download className="size-4" />} loading={exporting} onClick={download}>
            Export CSV
          </Button>
        }
      />
      <div className="sticky top-0 z-10 -mx-1 mt-6 flex flex-wrap items-center gap-3 bg-ink/85 px-1 py-2 backdrop-blur">
        <Segmented options={PERIODS} value={period} onChange={setPeriod} size="sm" />
        {data && (
          <span className="text-xs text-muted">
            {formatTime(data.start)} – {formatTime(data.end)} · per {data.bucket}
            {partial && (data.cost_tracked_since ? ` · ≈ costs tracked since ${formatTime(data.cost_tracked_since)}` : ' · ≈ no costs recorded yet')}
          </span>
        )}
      </div>
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!data && !error && <Spinner className="mt-10 size-6" />}

      {data && t && (
        <div className={`transition-opacity ${result?.period !== period ? 'opacity-60' : ''}`}>
          <section className="mt-6">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatTile label="Top-ups" value={formatUsd(t.topups)} hint={`+${formatUsd(t.bonuses)} bonuses · ${formatUsd(t.refunds)} refunds`} />
              <StatTile label="Charged" value={formatUsd(t.charged)} hint={`models ${formatUsd(t.charged_models)} · voices ${formatUsd(t.charged_voices)} · pictures ${formatUsd(t.charged_pictures)} · music ${formatUsd(t.charged_music)} · covers ${formatUsd(t.charged_cover)}`} />
              <StatTile label="Provider cost" value={formatUsd(t.cost)} hint={`OpenRouter ${formatUsd(t.cost_openrouter)} · ElevenLabs ${formatUsd(t.cost_elevenlabs)}`} />
              <StatTile label="Margin" value={formatUsd(t.margin)} hint="charged − refunds − provider cost" />
              <StatTile label="Effective markup" value={t.markup === null ? '—' : `× ${t.markup}`} hint={`charged ÷ cost of what we bill (${formatUsd(t.cost_billed)})`} />
              <StatTile label="Cost nobody pays" value={formatUsd(t.cost_unbilled)} hint="scenes, checks, structuring, trending" />
              <StatTile label="Credits held by users" value={formatUsd(data.liabilities)} hint={data.negative_balances ? `${data.negative_balances} below zero (${formatUsd(data.negative_total)})` : 'what we owe in service'} />
              <StatTile label="Adjustments" value={`+${formatUsd(t.adjustments_in)} / −${formatUsd(t.adjustments_out)}`} hint="manual changes in the console or app.manage" />
            </div>
          </section>

          <section className="mt-8">
            <SectionLabel className="mb-3">Over time</SectionLabel>
            <Charts data={data} />
          </section>

          <section className="mt-8 grid items-start gap-4 xl:grid-cols-3">
            <Panel title="Provider cost by purpose" aside="system keys">
              {purposes.length === 0 ? (
                <p className="px-4 py-4 text-sm text-muted">Nothing spent in this period.</p>
              ) : (
                <ul className="divide-y divide-line/70">
                  {purposes.map(([purpose, cost]) => (
                    <li key={purpose} className="flex items-center justify-between gap-3 px-4 py-2 text-xs">
                      <span className="text-text-2">
                        {PURPOSES[purpose] ?? purpose}
                        {!BILLED.has(purpose) && <span className="ml-1.5 text-muted">· not billed</span>}
                      </span>
                      <span className="font-semibold tabular-nums">{formatUsd(cost)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Top payers" aside="top-ups">
              <DataTable caption="Top payers" columns={accountColumns} rows={data.top_payers} rowKey={(a) => a.user_id} empty="No top-ups in this period." />
            </Panel>
            <Panel title="Top spenders" aside="charges">
              <DataTable caption="Top spenders" columns={accountColumns} rows={data.top_spenders} rowKey={(a) => a.user_id} empty="Nobody was charged in this period." />
            </Panel>
          </section>

          <section className="mt-8">
            <Panel title="Stripe against the ledger">
              {!stripe?.configured ? (
                <p className="px-4 py-4 text-sm text-muted">Stripe is not configured (STRIPE_SECRET_KEY): top-ups are off.</p>
              ) : stripe.error ? (
                <ErrorBox className="m-4">{stripe.error}</ErrorBox>
              ) : (
                <div className="grid gap-3 px-4 py-3 text-sm">
                  <div className="flex flex-wrap gap-x-8 gap-y-1 text-text-3">
                    <span>
                      Paid sessions: <span className="font-semibold text-text">{stripe.sessions}</span> ({formatUsd(stripe.paid_total)})
                    </span>
                    <span>
                      Credited top-ups: <span className="font-semibold text-text">{stripe.credited}</span> ({formatUsd(stripe.credited_total)})
                    </span>
                  </div>
                  {stripe.missing.length === 0 && stripe.unmatched.length === 0 ? (
                    <p className="text-ok">Every paid session was credited.</p>
                  ) : (
                    <>
                      {stripe.missing.map((m) => (
                        <p key={m.id} className="text-con">
                          Paid, not credited: {formatUsd(m.amount)} by {m.email ?? 'unknown'} on {formatTime(m.created)} ({m.id})
                        </p>
                      ))}
                      {stripe.unmatched.length > 0 && <p className="text-host">Credited without a paid session in the list: {stripe.unmatched.join(', ')}</p>}
                    </>
                  )}
                </div>
              )}
            </Panel>
          </section>
        </div>
      )}

      <SudoDialog
        open={askCode}
        onClose={() => setAskCode(false)}
        onConfirmed={() => {
          setAskCode(false);
          void download();
        }}
      />
    </Page>
  );
};

export default AdminFinance;
