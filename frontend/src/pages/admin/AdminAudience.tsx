import { useEffect, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ListFilter, RefreshCw } from 'lucide-react';
import { getAudience, getLiveVisits } from '../../api/admin/audience';
import type { Audience, AudienceRow, OverviewPeriod } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { DataTable } from '../../components/admin/DataTable';
import { StatTile } from '../../components/admin/StatTile';
import { TableCard } from '../../components/admin/TableCard';
import { Funnel } from '../../components/admin/audience/Funnel';
import { HourGrid } from '../../components/admin/audience/HourGrid';
import { ShareList } from '../../components/admin/audience/ShareList';
import { SourceText } from '../../components/admin/audience/VisitBits';
import { visitColumns } from '../../components/admin/audience/visitTable';
import { DEVICE_LABELS, SECTION_LABELS, VERDICT_COLORS, VERDICT_HINTS, VERDICT_LABELS, VERDICT_ORDER, countryName, duration, flagOf, isVerdict, languageName, sourceLabel } from '../../components/admin/audience/format';
import { ChartCard } from '../../components/admin/charts/ChartCard';
import { LineChart } from '../../components/admin/charts/LineChart';
import { StackedColumns } from '../../components/admin/charts/StackedColumns';
import { SERIES, SOURCE_COLORS } from '../../components/admin/charts/palette';
import { bucketLabel } from '../../components/admin/charts/scale';
import { formatPercent, formatTime } from '../../components/admin/helpers';
import { useLoad } from '../../components/admin/useLoad';
import { Button, Card, Chip, ErrorBox, SectionLabel, Segmented, Spinner } from '../../components/ui';
import { formatCount, formatDateShort } from '../../lib/format';

const PERIODS: { value: OverviewPeriod; label: string; previous: string }[] = [
  { value: '24h', label: '24 h', previous: 'vs previous 24 h' },
  { value: '7d', label: '7 days', previous: 'vs previous 7 days' },
  { value: '30d', label: '30 days', previous: 'vs previous 30 days' },
  { value: '90d', label: '90 days', previous: 'vs previous 90 days' },
  { value: 'all', label: 'All time', previous: '' },
];

type Tab = 'overview' | 'sources' | 'places' | 'content' | 'tech';
const TABS: { value: Tab; label: string }[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'sources', label: 'Sources' },
  { value: 'places', label: 'Places' },
  { value: 'content', label: 'Content' },
  { value: 'tech', label: 'Devices' },
];

const SOURCE_ORDER = ['search', 'ai', 'social', 'embed', 'other', 'direct', 'internal'] as const;
const count = (n: number) => formatCount(Math.round(n));
const timezone = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
})();

const pointLabel = (iso: string, bucket: Audience['bucket']) => {
  const date = new Date(iso);
  if (bucket === 'hour') return `${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' })}, ${bucketLabel(iso, 'hour')} UTC`;
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

/** A link to the visits list with this filter, on a breakdown's first cell. */
const VisitsLink = ({ period, filter, children }: { period: OverviewPeriod; filter: Record<string, string>; children: ReactNode }) => (
  <Link to={`/admin/audience/visits?${new URLSearchParams({ period, ...filter }).toString()}`} className="block max-w-72 truncate hover:text-text">
    {children}
  </Link>
);

const loadLive = () => getLiveVisits();

/** Visits active in the last five minutes, polled, with who made them. */
const LiveNow = () => {
  const { data, error } = useLoad(loadLive, 15_000);
  const visits = data?.visits ?? [];
  const people = visits.filter((v) => v.verdict === 'human' || v.verdict === 'likely_human').length;
  const automated = visits.filter((v) => v.verdict === 'bot' || v.verdict === 'agent').length;
  return (
    <Card padding="none" className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
        <span className="flex items-center gap-2 text-sm font-semibold text-text-2">
          <span className={`size-2 rounded-full ${visits.length ? 'animate-pulse bg-ok' : 'bg-surface-4'}`} aria-hidden />
          On the site now
          <span className="font-normal text-muted">
            {data ? `${visits.length} active in the last 5 minutes` : ''}
            {visits.length > 0 && ` · ${people} ${people === 1 ? 'person' : 'people'} · ${automated} ${automated === 1 ? 'bot or agent' : 'bots and agents'}`}
          </span>
        </span>
        {data && <span className="text-xs text-muted">updated {formatTime(data.generated_at)} · every 15 s</span>}
      </div>
      {error && <ErrorBox className="m-3">{error}</ErrorBox>}
      {visits.length > 0 ? (
        <DataTable caption="Visits now" columns={visitColumns()} rows={visits.slice(0, 20)} rowKey={(v) => v.id} rowHref={(v) => `/admin/audience/visits/${v.id}`} />
      ) : (
        data && <p className="px-4 py-4 text-sm text-muted">Nobody right now.</p>
      )}
    </Card>
  );
};

const Charts = ({ data }: { data: Audience }) => {
  const points = data.series;
  const labels = points.map((p) => pointLabel(p.t, data.bucket));
  const axisLabels = points.map((p) => bucketLabel(p.t, data.bucket));
  const people = [
    { key: 'visitors', label: 'Visitors', color: SERIES[0], values: points.map((p) => p.visitors) },
    { key: 'visits', label: 'Visits', color: SERIES[1], values: points.map((p) => p.visits) },
  ];
  const sources = SOURCE_ORDER.map((s) => ({ key: s, label: sourceLabel(s), color: SOURCE_COLORS[s], values: points.map((p) => p.sources[s] ?? 0) }));
  const table = (series: { label: string; values: number[] }[]) => ({ rowLabels: labels, columns: series.map((s) => ({ label: s.label, values: s.values.map(count) })) });
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ChartCard title="Visitors" subtitle="Distinct browsers and their visits" legend={people.map((s) => ({ label: s.label, color: s.color, shape: 'line' as const }))} table={table(people)}>
        <LineChart series={people} labels={labels} axisLabels={axisLabels} format={count} integer ariaLabel="Visitors and visits over time" />
      </ChartCard>
      <ChartCard title="Visits by source" subtitle="Where each visit came from" legend={sources.map((s) => ({ label: s.label, color: s.color, shape: 'square' as const }))} table={table(sources)}>
        <StackedColumns series={sources} labels={labels} axisLabels={axisLabels} format={count} ariaLabel="Visits by source over time" />
      </ChartCard>
    </div>
  );
};

/** Every visit of the period by verdict (bots included), each a link to its visits. */
const Verdicts = ({ data }: { data: Audience }) => {
  const order = (key: string) => (isVerdict(key) ? VERDICT_ORDER.indexOf(key) : VERDICT_ORDER.length);
  const rows = [...data.verdicts].sort((a, b) => order(a.key) - order(b.key));
  const total = rows.reduce((sum, row) => sum + row.visits, 0);
  const automated = rows.filter((row) => row.key === 'bot' || row.key === 'agent').reduce((sum, row) => sum + row.visits, 0);
  return (
    <TableCard
      title="People and bots"
      subtitle={
        data.bots
          ? 'Every visit by verdict; bots and AI agents are in the numbers above'
          : `Every visit by verdict; the ${count(automated)} by bots and AI agents are left out of the numbers above${total ? ` (${formatPercent(automated / total)})` : ''}`
      }
      head={['Verdict', 'Visits', 'Visitors', 'Time / visit', 'Bounce']}
      empty="No visits in this period."
      rows={rows.map((row) => [
        <VisitsLink key="v" period={data.period} filter={{ verdict: row.key }}>
          <span className="inline-flex items-center gap-2" title={isVerdict(row.key) ? VERDICT_HINTS[row.key] : undefined}>
            <span aria-hidden className="size-2 shrink-0 rounded-[3px]" style={{ background: isVerdict(row.key) ? VERDICT_COLORS[row.key] : undefined }} />
            {isVerdict(row.key) ? VERDICT_LABELS[row.key] : row.key}
          </span>
        </VisitsLink>,
        count(row.visits),
        count(row.visitors),
        duration(row.engaged_ms),
        formatPercent(row.bounce_rate),
      ])}
    />
  );
};

const rowCells = (row: AudienceRow) => [count(row.visits), count(row.visitors), duration(row.engaged_ms), formatPercent(row.bounce_rate), count(row.signups)];
const ROW_HEAD = ['Visits', 'Visitors', 'Time / visit', 'Bounce', 'Sign-ups'];

const Overview = ({ data, previous }: { data: Audience; previous: string }) => {
  const t = data.tiles;
  const visitors = t.visitors.value;
  return (
    <>
      <div className="mt-6">
        <LiveNow />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <StatTile label="Visitors" value={count(visitors)} current={visitors} previous={t.visitors.previous} previousLabel={previous} hint="distinct browsers" />
        <StatTile label="Visits" value={count(t.visits.value)} current={t.visits.value} previous={t.visits.previous} previousLabel={previous} />
        <StatTile
          label="Pages viewed"
          value={count(t.pageviews.value)}
          current={t.pageviews.value}
          previous={t.pageviews.previous}
          previousLabel={previous}
          hint={t.visits.value ? `${(t.pageviews.value / t.visits.value).toFixed(1)} per visit` : undefined}
        />
        <StatTile label="Time per visit" value={duration(t.engaged_ms.value)} current={Math.round(t.engaged_ms.value / 1000)} previous={t.engaged_ms.previous === null ? null : Math.round(t.engaged_ms.previous / 1000)} format={(s) => duration(s * 1000)} previousLabel={previous} hint="page in front, not idle" />
        <StatTile label="Bounce rate" value={formatPercent(t.visits.value ? t.bounce_rate.value : null)} current={t.bounce_rate.value} previous={t.bounce_rate.previous} upIsGood={false} format={(d) => formatPercent(d)} previousLabel={previous} hint="one page, under 10 s" />
        <StatTile label="New visitors" value={count(t.new_visitors.value)} current={t.new_visitors.value} previous={t.new_visitors.previous} previousLabel={previous} hint={visitors ? `${formatPercent(t.new_visitors.value / visitors)} of visitors` : undefined} />
        <StatTile label="Sign-ups" value={count(t.signups.value)} current={t.signups.value} previous={t.signups.previous} previousLabel={previous} hint={visitors ? `${formatPercent(t.signups.value / visitors)} of visitors` : undefined} />
      </div>
      <Section title="People and bots" aside="A verdict per visit from its browser, network and input; open a visit to see why">
        <Verdicts data={data} />
      </Section>
      <Section title="Over time">
        <Charts data={data} />
      </Section>
      <Section title="Behaviour">
        <div className="grid items-start gap-4 xl:grid-cols-[1fr_1.4fr]">
          <Funnel steps={data.funnel} />
          <HourGrid hours={data.hours} timezone={data.timezone} />
        </div>
        <div className="mt-4">
          <TableCard
            title="What visitors did"
            subtitle="Actions the site reports, how often and by how many visitors"
            head={['Action', 'Times', 'Visitors']}
            empty="No actions in this period."
            rows={data.actions.map((row) => [
              <VisitsLink key="a" period={data.period} filter={{ action: row.key }}>
                {row.label ?? row.key}
              </VisitsLink>,
              count(row.visits),
              count(row.visitors),
            ])}
          />
        </div>
      </Section>
    </>
  );
};

const Sources = ({ data }: { data: Audience }) => (
  <div className="mt-6 grid gap-4">
    <TableCard
      title="Sources"
      subtitle="Where visits came from: the landing page's referrer (or campaign)"
      head={['Source', ...ROW_HEAD]}
      empty="No visits in this period."
      rows={data.sources.map((row) => [
        <VisitsLink key="s" period={data.period} filter={{ source: row.key }}>
          <SourceText source={row.key} />
        </VisitsLink>,
        ...rowCells(row),
      ])}
    />
    <div className="grid items-start gap-4 xl:grid-cols-2">
      <TableCard
        title="Referring sites"
        subtitle="Hosts that sent visitors"
        head={['Site', 'Visits', 'Visitors', 'Sign-ups']}
        empty="No referring sites in this period."
        rows={data.referrers.map((row) => [
          <VisitsLink key="h" period={data.period} filter={{ q: row.key }}>
            {row.key} <span className="text-muted">· {sourceLabel(row.label ?? '')}</span>
          </VisitsLink>,
          count(row.visits),
          count(row.visitors),
          count(row.signups),
        ])}
      />
      <TableCard
        title="Campaigns"
        subtitle="Links with utm_source / utm_medium / utm_campaign"
        head={['Campaign', 'Visits', 'Visitors', 'Sign-ups']}
        empty="No tagged links in this period. Add ?utm_source=…&utm_campaign=… to the links you post."
        rows={data.campaigns.map((row) => [
          <span key="c" className="block max-w-72 truncate" title={[row.utm_source, row.utm_medium, row.utm_campaign].filter(Boolean).join(' / ')}>
            {row.utm_campaign ?? '—'} <span className="text-muted">{[row.utm_source, row.utm_medium].filter(Boolean).join(' / ')}</span>
          </span>,
          count(row.visits),
          count(row.visitors),
          count(row.signups),
        ])}
      />
    </div>
  </div>
);

const Places = ({ data }: { data: Audience }) => (
  <div className="mt-6 grid gap-4">
    {!data.geo.available && (
      <Card padding="sm" className="text-sm text-muted">
        No IP → place database yet: places stay unknown until the background queue fetches it (or run <code className="font-mono">python -m app.manage geoip update</code>); visits saved meanwhile are placed then.
      </Card>
    )}
    <TableCard
      title="Countries"
      head={['Country', ...ROW_HEAD]}
      empty="No visits in this period."
      rows={data.countries.map((row) => [
        <VisitsLink key="c" period={data.period} filter={row.key ? { country: row.key } : {}}>
          {flagOf(row.key)} {countryName(row.key)}
        </VisitsLink>,
        ...rowCells(row),
      ])}
    />
    <div className="grid items-start gap-4 xl:grid-cols-2">
      <TableCard
        title="Regions"
        head={['Region', 'Visits', 'Visitors', 'Sign-ups']}
        empty="No regions known in this period."
        rows={data.regions.map((row) => [
          <VisitsLink key="r" period={data.period} filter={{ country: row.key, q: row.label ?? '' }}>
            {flagOf(row.key)} {row.label} <span className="text-muted">· {countryName(row.key)}</span>
          </VisitsLink>,
          count(row.visits),
          count(row.visitors),
          count(row.signups),
        ])}
      />
      <TableCard
        title="Cities"
        head={['City', 'Visits', 'Visitors', 'Sign-ups']}
        empty="No cities known in this period."
        rows={data.cities.map((row) => [
          <span key="c" className="block max-w-72 truncate">
            {flagOf(row.key)} {row.label}
          </span>,
          count(row.visits),
          count(row.visitors),
          count(row.signups),
        ])}
      />
    </div>
  </div>
);

const Content = ({ data }: { data: Audience }) => (
  <div className="mt-6 grid gap-4">
    <div className="grid items-start gap-4 xl:grid-cols-[1fr_2fr]">
      <ShareList
        title="Parts of the site"
        subtitle="Pages viewed, with the time a page stays in front"
        items={data.sections.map((row) => ({ key: row.key, label: SECTION_LABELS[row.key] ?? row.key, value: row.visits, extra: duration(row.engaged_ms) }))}
      />
      <TableCard
        title="Pages"
        subtitle="Most viewed, with the time each stays in front"
        head={['Page', 'Views', 'Visitors', 'Time / view']}
        empty="No pages viewed in this period."
        rows={data.pages.map((row) => [
          <span key="p" className="flex max-w-96 min-w-0 flex-col">
            {row.title && <span className="truncate text-text-2">{row.title}</span>}
            <span className="truncate font-mono text-[11px] text-muted" title={row.path}>
              {row.path}
            </span>
          </span>,
          count(row.views),
          count(row.visitors),
          duration(row.engaged_ms),
        ])}
      />
    </div>
    <div className="grid items-start gap-4 xl:grid-cols-2">
      <TableCard
        title="Landing pages"
        subtitle="Where visits begin"
        head={['Page', 'Visits', 'Bounce', 'Sign-ups']}
        empty="No visits in this period."
        rows={data.landing.map((row) => [
          <VisitsLink key="l" period={data.period} filter={{ q: row.key }}>
            <span className="font-mono text-[11px]">{row.key}</span>
          </VisitsLink>,
          count(row.visits),
          formatPercent(row.bounce_rate),
          count(row.signups),
        ])}
      />
      <TableCard
        title="Exit pages"
        subtitle="The last page of a visit"
        head={['Page', 'Visits', 'Time / visit']}
        empty="No visits in this period."
        rows={data.exits.map((row) => [<span key="e" className="block max-w-80 truncate font-mono text-[11px]">{row.key}</span>, count(row.visits), duration(row.engaged_ms)])}
      />
    </div>
    <TableCard
      title="Videos watched"
      subtitle="Plays on debate pages and how many reached the end"
      head={['Debate', 'Plays', 'Viewers', 'To the end']}
      empty="No video was played in this period."
      rows={data.videos.map((row) => [
        <Link key="v" to={`/admin/debates/${row.debate_id}`} className="block max-w-96 truncate hover:text-text" title={row.title}>
          {row.title}
        </Link>,
        count(row.plays),
        count(row.visitors),
        `${count(row.finished)} · ${formatPercent(row.plays ? row.finished / row.plays : null)}`,
      ])}
    />
  </div>
);

const Tech = ({ data }: { data: Audience }) => {
  const items = (rows: AudienceRow[], label: (key: string) => string = (k) => k || 'Unknown') => rows.map((row) => ({ key: row.key || 'unknown', label: label(row.key), value: row.visits, extra: duration(row.engaged_ms) }));
  return (
    <div className="mt-6 grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
      <ShareList title="Devices" subtitle="Visits, with the time per visit" items={items(data.devices, (k) => DEVICE_LABELS[k] ?? k)} />
      <ShareList title="Browsers" items={items(data.browsers)} />
      <ShareList title="Systems" items={items(data.systems)} />
      <ShareList title="Browser languages" items={items(data.languages, (k) => (k ? `${languageName(k)} (${k})` : 'Unknown'))} />
      <ShareList title="Screens" items={items(data.screens)} />
    </div>
  );
};

const AdminAudience = () => {
  const [params, setParams] = useSearchParams();
  const tab = TABS.find((t) => t.value === params.get('tab'))?.value ?? 'overview';
  const [period, setPeriod] = useState<OverviewPeriod>('7d');
  const [staff, setStaff] = useState(false);
  const [bots, setBots] = useState(false);
  const [refreshes, setRefreshes] = useState(0);
  const [data, setData] = useState<Audience | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAudience(period, timezone, staff, bots, refreshes > 0)
      .then((value) => {
        if (!cancelled) {
          setData(value);
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
  }, [period, staff, bots, refreshes]);

  const choose = (value: OverviewPeriod) => {
    setLoading(true);
    setPeriod(value);
  };
  const showTab = (value: Tab) => {
    const next = new URLSearchParams(params);
    if (value === 'overview') next.delete('tab');
    else next.set('tab', value);
    setParams(next, { replace: true });
  };
  const previous = PERIODS.find((p) => p.value === period)?.previous ?? '';
  const partial = data?.data_since && new Date(data.start) < new Date(data.data_since);

  return (
    <Page>
      <PageTitle
        kicker="Admin console"
        title="Audience"
        right={
          <Link to={`/admin/audience/visits?period=${period}`} className="inline-flex items-center gap-1.5 text-sm text-accent hover:text-accent-hover">
            <ListFilter className="size-4" /> Every visit →
          </Link>
        }
      />
      <div className="sticky top-0 z-10 -mx-1 mt-6 flex flex-wrap items-center gap-3 bg-ink/85 px-1 py-2 backdrop-blur">
        <Segmented options={PERIODS.map((p) => ({ value: p.value, label: p.label }))} value={period} onChange={choose} size="sm" />
        <Chip
          size="sm"
          active={staff}
          onClick={() => {
            setLoading(true);
            setStaff((v) => !v);
          }}
          title="Visits of accounts with a console role are left out unless this is on"
        >
          Include staff
        </Chip>
        <Chip
          size="sm"
          active={bots}
          onClick={() => {
            setLoading(true);
            setBots((v) => !v);
          }}
          title="Visits judged to be bots or AI agents are left out of the numbers unless this is on"
        >
          Include bots
        </Chip>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setLoading(true);
            setRefreshes((n) => n + 1);
          }}
          disabled={loading}
          icon={loading ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" />}
        >
          Refresh
        </Button>
        {data && <span className="text-xs text-muted">Updated {formatTime(data.generated_at)} · UTC buckets</span>}
      </div>
      <div className="mt-3">
        <Segmented options={TABS} value={tab} onChange={showTab} />
      </div>

      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!data && !error && <Spinner className="mt-10 size-6" />}
      {data && (
        <div className={`transition-opacity ${loading ? 'opacity-60' : ''}`}>
          {partial && <p className="mt-4 text-xs text-muted">≈ visits are recorded since {formatDateShort(data.data_since ?? '', 'UTC')}: the period reaches further back.</p>}
          {!data.data_since && <p className="mt-4 text-xs text-muted">No visit recorded yet: the site reports them from its next page view on.</p>}
          {tab === 'overview' && <Overview data={data} previous={previous} />}
          {tab === 'sources' && <Sources data={data} />}
          {tab === 'places' && <Places data={data} />}
          {tab === 'content' && <Content data={data} />}
          {tab === 'tech' && <Tech data={data} />}
          <p className="mt-8 text-xs text-muted">
            Time counts while a page is visible and its visitor active in the last 15 minutes. IP addresses are cleared after the days set in{' '}
            <Link to="/admin/settings" className="text-accent hover:text-accent-hover">
              Settings → Audience
            </Link>
            .{data.geo.attribution && ` ${data.geo.attribution}${data.geo.release ? `, release ${data.geo.release}` : ''}.`}
          </p>
        </div>
      )}
    </Page>
  );
};

export default AdminAudience;
