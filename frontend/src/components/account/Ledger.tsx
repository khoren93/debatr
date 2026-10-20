import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { AudioLines, Diamond, Download, Gift, ImageIcon, Music, Plus, Receipt, RotateCcw, SlidersHorizontal } from 'lucide-react';
import { exportTransactions, listTransactions } from '../../api/billing';
import { getErrorMessage } from '../../api/client';
import type { Transaction } from '../../api/types';
import { formatDateShort, formatSigned } from '../../lib/format';
import { downloadText } from '../debate/helpers';
import { Button, EmptyState, ErrorBox, SectionLabel, Spinner, useToast } from '../ui';
import { clockTime, humanizeKind, localDay, money } from './helpers';

const PAGE = 50;

const CATEGORIES: Record<string, { label: string; icon: ReactNode; tone: string }> = {
  models: { label: 'Model tokens', icon: <Diamond className="size-4" />, tone: 'bg-pro/14 text-pro' },
  voices: { label: 'Premium voices', icon: <AudioLines className="size-4" />, tone: 'bg-host/14 text-host' },
  pictures: { label: 'AI pictures', icon: <ImageIcon className="size-4" />, tone: 'bg-violet/14 text-violet' },
  music: { label: 'Battle music', icon: <Music className="size-4" />, tone: 'bg-con/14 text-con' },
  topup: { label: 'Top-up', icon: <Plus className="size-4" strokeWidth={2.5} />, tone: 'bg-ok/14 text-ok' },
  bonus: { label: 'Bonus', icon: <Gift className="size-4" />, tone: 'bg-ok/14 text-ok' },
  refund: { label: 'Refund', icon: <RotateCcw className="size-4" />, tone: 'bg-ok/14 text-ok' },
  adjustment: { label: 'Adjustment', icon: <SlidersHorizontal className="size-4" />, tone: 'bg-surface-3 text-muted' },
};

const categoryOf = (t: Transaction) =>
  CATEGORIES[t.category] ?? { label: humanizeKind(t.kind), icon: <Receipt className="size-4" />, tone: 'bg-surface-3 text-muted' };

const ROW = 'grid grid-cols-[38px_minmax(0,1fr)_auto] items-center gap-3.5 border-b border-white/4 px-[clamp(18px,2.6vw,24px)] last:border-b-0';

/** One ledger line: category tile, title (links to the debate), category · time, amount and balance. */
const LedgerRow = ({ tx, when, wrap }: { tx: Transaction; when: string; wrap: boolean }) => {
  const cat = categoryOf(tx);
  // line-clamp sets its own display, so only the one-line variant needs `block`.
  const text = wrap ? 'line-clamp-2 leading-[1.4]' : 'block truncate';
  return (
    <li className={`${ROW} ${wrap ? 'py-3' : 'py-3.5'}`}>
      <div className={`grid size-[38px] place-items-center rounded-[11px] ${cat.tone}`} aria-hidden="true">
        {cat.icon}
      </div>
      <div className="min-w-0">
        {tx.debate_id ? (
          <Link to={`/debate/${tx.debate_id}`} className={`text-sm font-semibold hover:underline ${text}`} title={tx.title}>
            {tx.title}
          </Link>
        ) : (
          <div className={`text-sm font-semibold ${text}`} title={tx.title}>
            {tx.title}
          </div>
        )}
        <div className="mt-[3px] truncate text-xs text-muted">
          {cat.label} · {when}
        </div>
      </div>
      <div className="text-right">
        <div className={`font-mono text-sm ${tx.amount_usd > 0 ? 'text-ok' : 'text-text'}`}>{formatSigned(tx.amount_usd)}</div>
        <div className="mt-[3px] font-mono text-[11px] text-dim">bal {money(tx.balance_after_usd)}</div>
      </div>
    </li>
  );
};

const Panel = ({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) => (
  <section className="rounded-panel border border-line bg-surface">
    <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-line px-[clamp(18px,2.6vw,24px)] py-[18px]">
      <SectionLabel>{title}</SectionLabel>
      {action}
    </div>
    {children}
  </section>
);

const Loading = ({ children }: { children: string }) => (
  <div className="flex items-center gap-2 px-[clamp(18px,2.6vw,24px)] py-6 text-xs text-muted">
    <Spinner className="size-4" /> {children}
  </div>
);

const Empty = () => (
  <EmptyState className="m-4" icon={<Receipt className="size-5" />} title="No transactions yet" text="Top-ups and debate charges will show up here." />
);

/** RECENT ACTIVITY on the overview: the latest few ledger rows. */
export const RecentActivityCard = ({ items, error, onViewAll }: { items: Transaction[] | null; error: string | null; onViewAll: () => void }) => (
  <Panel
    title="Recent activity"
    action={
      <button type="button" onClick={onViewAll} className="cursor-pointer text-[13px] text-accent hover:text-accent-hover">
        View all
      </button>
    }
  >
    {error ? (
      <ErrorBox className="m-4">{error}</ErrorBox>
    ) : items === null ? (
      <Loading>Loading activity…</Loading>
    ) : items.length === 0 ? (
      <Empty />
    ) : (
      <ul>
        {items.map((t) => (
          <LedgerRow key={t.id} tx={t} when={formatDateShort(t.created_at)} wrap={false} />
        ))}
      </ul>
    )}
  </Panel>
);

/** Rows grouped by local calendar day, newest first. */
const groupByDay = (items: Transaction[]) => {
  const groups: { day: string; label: string; rows: Transaction[] }[] = [];
  for (const t of items) {
    const day = localDay(t.created_at);
    const last = groups.at(-1);
    if (last?.day === day) last.rows.push(t);
    else groups.push({ day, label: formatDateShort(t.created_at), rows: [t] });
  }
  return groups;
};

/** LEDGER on the Billing tab: every top-up and charge, paged, with a CSV export. */
export const LedgerCard = ({ reloadKey }: { reloadKey: number }) => {
  const toast = useToast();
  const [items, setItems] = useState<Transaction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listTransactions(PAGE)
      .then((rows) => {
        if (cancelled) return;
        setItems(rows);
        setHasMore(rows.length === PAGE);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const loadMore = async () => {
    if (!items) return;
    setLoadingMore(true);
    try {
      const rows = await listTransactions(PAGE, items.length);
      const seen = new Set(items.map((t) => t.id));
      setItems([...items, ...rows.filter((t) => !seen.has(t.id))]);
      setHasMore(rows.length === PAGE);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setLoadingMore(false);
    }
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      const { text, name } = await exportTransactions();
      downloadText(text, name, 'text/csv');
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  return (
    <Panel
      title="Ledger"
      action={
        items && items.length > 0 ? (
          <Button size="sm" variant="secondary" onClick={exportCsv} loading={exporting} icon={<Download className="size-3.5" />}>
            Export CSV
          </Button>
        ) : undefined
      }
    >
      {error ? (
        <ErrorBox className="m-4">{error}</ErrorBox>
      ) : items === null ? (
        <Loading>Loading transactions…</Loading>
      ) : items.length === 0 ? (
        <Empty />
      ) : (
        <>
          {groupByDay(items).map((g) => (
            <div key={g.day}>
              <div className="px-[clamp(18px,2.6vw,24px)] pt-3.5 pb-1.5 font-mono text-[11px] tracking-[0.06em] text-dim uppercase">{g.label}</div>
              <ul>
                {g.rows.map((t) => (
                  <LedgerRow key={t.id} tx={t} when={clockTime(t.created_at)} wrap />
                ))}
              </ul>
            </div>
          ))}
          {hasMore && (
            <div className="border-t border-line p-3 text-center">
              <Button size="sm" variant="ghost" onClick={loadMore} loading={loadingMore}>
                Show older
              </Button>
            </div>
          )}
        </>
      )}
    </Panel>
  );
};
