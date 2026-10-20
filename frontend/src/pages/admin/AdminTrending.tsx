import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { ArrowUpRight, Eye, EyeOff, RefreshCw } from 'lucide-react';
import { buildTrendingNow, getTrendingBatch, listTrendingBatches, setTopicHidden } from '../../api/admin/debates';
import type { Page as PageOf, TrendingBatchCard, TrendingBatchRow, TrendingTopicRow } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { DataTable, Pager, type Column } from '../../components/admin/DataTable';
import { Panel } from '../../components/admin/users/UserSections';
import { formatTime, formatUsd } from '../../components/admin/helpers';
import { Button, ConfirmDialog, ErrorBox, Spinner, useToast } from '../../components/ui';
import { sourceDomain } from '../../lib/format';
import { formatSpec } from '../../lib/formats';

const PAGE = 20;
const ratio = (a: number | null, b: number | null) => (a === null ? '—' : b === null ? String(a) : `${a}/${b}`);

/** A format's list: its topics' chip ("debate" lists go without one, as before formats). */
const FormatChip = ({ format }: { format: string | undefined }) =>
  format && format !== 'debate' ? (
    <span className="rounded-[5px] bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] tracking-[0.04em] text-text-3">{formatSpec(format).label}</span>
  ) : null;

const AdminTrending = () => {
  const { me } = useAdminAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [batches, setBatches] = useState<{ key: string; page: PageOf<TrendingBatchRow> } | null>(null);
  const [card, setCard] = useState<TrendingBatchCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyTopic, setBusyTopic] = useState<string | null>(null);
  const [confirmBuild, setConfirmBuild] = useState(false);
  const [building, setBuilding] = useState(false);
  const listKey = `${offset}:${version}`;

  useEffect(() => {
    let cancelled = false;
    listTrendingBatches(offset, PAGE)
      .then((page) => {
        if (!cancelled) {
          setBatches({ key: `${offset}:${version}`, page });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [offset, version]);

  const rows = batches?.page.rows ?? [];
  const chosen = params.get('batch') ?? rows.find((b) => b.current)?.id ?? rows[0]?.id ?? null;

  useEffect(() => {
    if (!chosen) return;
    let cancelled = false;
    getTrendingBatch(chosen)
      .then((data) => {
        if (!cancelled) setCard(data);
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [chosen, version]);

  const toggle = async (topic: TrendingTopicRow) => {
    setBusyTopic(topic.id);
    try {
      const out = await setTopicHidden(topic.id, !topic.is_hidden);
      toast.success(out.message);
      setVersion((n) => n + 1);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusyTopic(null);
    }
  };

  const build = async () => {
    setBuilding(true);
    try {
      toast.success((await buildTrendingNow()).message);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBuilding(false);
      setConfirmBuild(false);
    }
  };

  const batchColumns: Column<TrendingBatchRow>[] = [
    {
      key: 'when',
      header: 'Built',
      className: 'whitespace-nowrap',
      cell: (b) => (
        <span className="flex items-center gap-2">
          <span className={b.id === chosen ? 'font-semibold text-text' : 'text-text-2'}>{formatTime(b.created_at)}</span>
          {b.current && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-bold uppercase text-accent">Live</span>}
        </span>
      ),
    },
    { key: 'topics', header: 'Topics', align: 'right', cell: (b) => (b.hidden ? `${b.topic_count} (${b.hidden} hidden)` : b.topic_count) },
    { key: 'feeds', header: 'Feeds', align: 'right', className: 'text-text-3', cell: (b) => ratio(b.feeds_ok, b.feeds_total) },
    { key: 'headlines', header: 'Headlines · blocked · sent', align: 'right', className: 'whitespace-nowrap text-text-3', cell: (b) => `${b.headlines_fresh ?? '—'} · ${b.headlines_blocked ?? '—'} · ${b.headlines_sent ?? '—'}` },
    { key: 'dropped', header: 'Dropped', align: 'right', className: 'text-text-3', cell: (b) => b.dropped },
    { key: 'cost', header: 'Cost', align: 'right', cell: (b) => formatUsd(b.cost_usd) },
    {
      key: 'open',
      header: <span className="sr-only">Open</span>,
      align: 'right',
      cell: (b) => (
        <Button variant="ghost" size="sm" onClick={() => setParams({ batch: b.id }, { replace: true })} disabled={b.id === chosen}>
          {b.id === chosen ? 'Shown' : 'Show'}
        </Button>
      ),
    },
  ];

  const topicColumns: Column<TrendingTopicRow>[] = [
    { key: 'rank', header: '#', className: 'w-8 text-muted', cell: (t) => t.rank },
    {
      key: 'question',
      header: 'Topic',
      cell: (t) => (
        <span className={`flex min-w-0 max-w-[560px] flex-col ${t.is_hidden ? 'opacity-50' : ''}`}>
          <span className="flex flex-wrap items-center gap-2 font-semibold text-text-2">
            <FormatChip format={t.format} />
            {t.question}
          </span>
          <span className="text-xs text-muted">
            {t.label} · {t.category} · heat {t.heat} · {t.outlets} outlet{t.outlets === 1 ? '' : 's'}
          </span>
          {t.brief && <span className="mt-0.5 line-clamp-2 text-xs text-text-3">{t.brief}</span>}
          <span className="mt-0.5 flex flex-wrap gap-x-2 text-[11px]">
            {t.sources.map((s, i) =>
              s.url ? (
                <a key={i} href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-muted hover:text-text">
                  {s.outlet || sourceDomain(s.url)} <ArrowUpRight className="size-3" />
                </a>
              ) : null,
            )}
          </span>
        </span>
      ),
    },
    {
      key: 'hide',
      header: <span className="sr-only">Hide or show</span>,
      align: 'right',
      cell: (t) => (
        <Button
          variant={t.is_hidden ? 'secondary' : 'ghost'}
          size="sm"
          loading={busyTopic === t.id}
          icon={t.is_hidden ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
          onClick={() => toggle(t)}
        >
          {t.is_hidden ? 'Show' : 'Hide'}
        </Button>
      ),
    },
  ];

  return (
    <Page>
      <PageTitle
        kicker="Admin console"
        title="Trending topics"
        right={
          me?.permissions.includes('system') && (
            <Button variant="secondary" size="sm" icon={<RefreshCw className="size-4" />} onClick={() => setConfirmBuild(true)}>
              Build a batch now
            </Button>
          )
        }
      />
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!batches && !error && <Spinner className="mt-10 size-6" />}

      {batches && (
        <div className="mt-6 grid gap-4">
          <Panel title="Batches" aside="the newest one is on the site">
            <DataTable caption="Batches" columns={batchColumns} rows={rows} rowKey={(b) => b.id} loading={batches.key !== listKey} empty="No batches yet." />
            <Pager offset={offset} limit={PAGE} total={batches.page.total} onChange={setOffset} />
          </Panel>

          {card && (
            <>
              <Panel title={`Topics of ${formatTime(card.batch.created_at)}`} aside={`${card.batch.model} · ${formatUsd(card.batch.cost_usd)}`}>
                {card.batch.formats.length > 0 && (
                  <ul className="flex flex-wrap gap-x-5 gap-y-1 border-b border-line/70 px-4 py-2.5 text-xs text-text-3">
                    {card.batch.formats.map((f) => (
                      <li key={f.format}>
                        <span className="font-semibold text-text-2">{formatSpec(f.format).name}</span>{' '}
                        {f.error ? <span className="text-host">failed: {f.error} (the site keeps an older list)</span> : `${f.kept ?? '—'} kept of ${f.asked ?? '—'} asked`}
                      </li>
                    ))}
                  </ul>
                )}
                <DataTable caption="Topics" columns={topicColumns} rows={card.topics} rowKey={(t) => t.id} empty="No topics." />
              </Panel>
              <div className="grid items-start gap-4 lg:grid-cols-2">
                <Panel title="Dropped topics" aside={`${card.dropped.length}`}>
                  {card.dropped.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-muted">None.</p>
                  ) : (
                    <ul className="max-h-96 divide-y divide-line/70 overflow-y-auto">
                      {card.dropped.map((d, i) => (
                        <li key={i} className="px-4 py-2.5 text-xs">
                          <div className="flex flex-wrap items-center gap-2 text-text-2">
                            <FormatChip format={d.format} />
                            {d.question ?? '—'}
                          </div>
                          <div className="text-muted">{d.reason ?? ''}</div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
                <Panel title="Blocked headlines" aside={`${card.blocked.length} shown`}>
                  {card.blocked.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-muted">None.</p>
                  ) : (
                    <ul className="max-h-96 divide-y divide-line/70 overflow-y-auto">
                      {card.blocked.map((b, i) => (
                        <li key={i} className="px-4 py-2.5 text-xs">
                          <div className="text-text-2">{b.title ?? '—'}</div>
                          {b.term && <div className="font-mono text-[11px] text-muted">matched “{b.term}”</div>}
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
              </div>
            </>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmBuild}
        title="Build a new batch now?"
        body="It reads the news feeds and asks the model for debate and rap battle topics (about a minute, a few cents). The new batch replaces the one on the site."
        confirmLabel="Build"
        busy={building}
        onConfirm={build}
        onClose={() => setConfirmBuild(false)}
      />
    </Page>
  );
};

export default AdminTrending;
