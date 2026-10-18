import { useEffect, useState, type ReactNode } from 'react';
import { TriangleAlert } from 'lucide-react';
import type { AdminLedgerRow, AdminUserCard, AdminUserDebate, AuditEntry, Page, UserApiToken, UserPeriodStats } from '../../../api/admin/types';
import { getUserDebates, getUserLedger, revokeUserTokens } from '../../../api/admin/users';
import { getErrorMessage } from '../../../api/client';
import { formatAgo, formatCount, formatDateShort, formatSigned, formatTokens, shortModelName, STATUS_COLORS, STATUS_LABELS } from '../../../lib/format';
import type { DebateStatus } from '../../../api/types';
import { Button, Card, ErrorBox, ModelIcon, SectionLabel, Spinner, useToast } from '../../ui';
import { ActionDialog } from '../ActionDialog';
import { DataTable, Pager, type Column } from '../DataTable';
import { StatTile } from '../StatTile';
import { ChartCard } from '../charts/ChartCard';
import { StackedColumns } from '../charts/StackedColumns';
import { SPEND_COLORS } from '../charts/palette';
import { bucketLabel } from '../charts/scale';
import { formatPercent, formatTime, formatUsd } from '../helpers';

const CATEGORY_LABELS: Record<string, string> = {
  models: 'Model tokens',
  voices: 'Premium voices',
  pictures: 'AI pictures',
  topup: 'Top-up',
  bonus: 'Bonus',
  refund: 'Refund',
  adjustment: 'Adjustment',
};

export const Panel = ({ title, aside, children, className = '' }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) => (
  <Card padding="none" className={`min-w-0 overflow-hidden ${className}`}>
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
      <SectionLabel>{title}</SectionLabel>
      {aside && <div className="text-xs text-muted">{aside}</div>}
    </div>
    {children}
  </Card>
);

const count = (n: number) => formatCount(Math.round(n));

/** The account's numbers for one period. */
export const StatsGrid = ({ stats }: { stats: UserPeriodStats }) => {
  const s = stats.spent_by;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <StatTile label="Debates" value={count(stats.debates)} hint={`${stats.completed} completed · ${stats.failed} failed · ${stats.stopped} stopped`} />
      <StatTile label="Error rate" value={formatPercent(stats.error_rate)} hint="of finished debates" />
      <StatTile label="Spent" value={formatUsd(stats.spent)} hint={`models ${formatUsd(s.models)} · voices ${formatUsd(s.voices)} · pictures ${formatUsd(s.pictures)}`} />
      <StatTile label="Topped up" value={formatUsd(stats.topped_up)} hint={stats.credited ? `+${formatUsd(stats.credited)} bonuses, refunds, adjustments` : 'Stripe top-ups'} />
      <StatTile label="Model cost per debate" value={stats.avg_debate_cost === null ? '—' : formatUsd(stats.avg_debate_cost)} hint="charged per finished debate" />
      <StatTile label="Cost to us" value={formatUsd(stats.cost_system)} hint={`system keys · margin ${formatUsd(stats.spent - stats.cost_system)}`} />
      <StatTile label="Free · paid models" value={`${count(stats.free_debates)} · ${count(stats.paid_debates)}`} hint={`${stats.own_key_debates} on own key · ${stats.token_debates} via API`} />
      <StatTile label="Tokens" value={formatTokens(stats.tokens_in + stats.tokens_out)} hint={`${formatTokens(stats.tokens_in)} in · ${formatTokens(stats.tokens_out)} out`} />
    </div>
  );
};

/** Charges per UTC day for the last 30 days, stacked by what they paid for. */
export const SpendChart = ({ days }: { days: AdminUserCard['spend_days'] }) => {
  const total = days.reduce((sum, d) => sum + d.models + d.voices + d.pictures, 0);
  const labels = days.map((d) => new Date(d.day).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }));
  const axisLabels = days.map((d) => bucketLabel(d.day, 'day'));
  const series = (['models', 'voices', 'pictures'] as const).map((key) => ({
    key,
    label: CATEGORY_LABELS[key],
    color: SPEND_COLORS[key],
    values: days.map((d) => d[key]),
  }));
  if (total === 0) {
    return (
      <Card padding="sm">
        <h3 className="text-sm font-semibold text-text-2">Spending per day</h3>
        <p className="mt-3 text-sm text-muted">Nothing charged in the last 30 days.</p>
      </Card>
    );
  }
  return (
    <ChartCard
      title="Spending per day"
      subtitle={`${formatUsd(total)} in the last 30 days (UTC days)`}
      legend={series.map((s) => ({ label: s.label, color: s.color, shape: 'square' as const }))}
      table={{ rowLabels: labels, columns: series.map((s) => ({ label: s.label, values: s.values.map(formatUsd) })) }}
    >
      <StackedColumns series={series} labels={labels} axisLabels={axisLabels} format={formatUsd} ariaLabel="Credits charged per day by category" />
    </ChartCard>
  );
};

export const FavoriteModels = ({ models }: { models: AdminUserCard['favorite_models'] }) => {
  const top = models[0]?.debates ?? 0;
  return (
    <Panel title="Favourite models">
      {models.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted">No debates yet.</p>
      ) : (
        <ul className="grid gap-2.5 px-4 py-3">
          {models.map((m) => (
            <li key={m.model}>
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="flex min-w-0 items-center gap-2 text-text-2">
                  <ModelIcon modelId={m.model} size={14} />
                  <span className="truncate" title={m.model}>
                    {shortModelName(m.model)}
                  </span>
                </span>
                <span className="font-semibold tabular-nums">{m.debates}</span>
              </div>
              <div className="mt-1 h-1 rounded-full bg-surface-3">
                <div className="h-1 rounded-full bg-text-3" style={{ width: `${Math.max(4, (m.debates / (top || 1)) * 100)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
};

/** Likes and votes the account gave; most of them going to one owner looks like boosting. */
export const ReactionsPanel = ({ reactions }: { reactions: AdminUserCard['reactions'] }) => {
  const given = reactions.likes_given + reactions.votes_given;
  return (
    <Panel title="Likes and votes given" aside={`${reactions.likes_given} likes · ${reactions.votes_given} votes`}>
      {reactions.owners.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted">None yet.</p>
      ) : (
        <ul className="divide-y divide-line/70">
          {reactions.owners.map((o) => {
            const share = given ? (o.likes + o.votes) / given : 0;
            const suspicious = given >= 5 && share >= 0.5;
            return (
              <li key={o.user_id ?? 'gone'} className="flex items-center gap-3 px-4 py-2.5 text-xs">
                <span className="min-w-0 flex-1 truncate text-text-2">
                  {o.email ?? <span className="text-muted">a deleted or legacy owner</span>}
                </span>
                {suspicious && (
                  <span className="flex items-center gap-1 text-host" title="Most of this account's likes and votes go to one owner">
                    <TriangleAlert className="size-3.5" /> {Math.round(share * 100)}%
                  </span>
                )}
                <span className="whitespace-nowrap tabular-nums text-text-3">
                  {o.likes} likes · {o.votes} votes
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
};

/** The account's API tokens, revocable one by one or all at once. */
export const TokensPanel = ({ userId, tokens, onChanged }: { userId: string; tokens: UserApiToken[]; onChanged: () => void }) => {
  const toast = useToast();
  const [target, setTarget] = useState<UserApiToken | 'all' | null>(null);
  const columns: Column<UserApiToken>[] = [
    {
      key: 'name',
      header: 'Token',
      cell: (t) => (
        <span className="flex flex-col">
          <span className="font-semibold text-text-2">{t.name}</span>
          <span className="font-mono text-[11px] text-muted">{t.token_hint}</span>
        </span>
      ),
    },
    { key: 'limit', header: 'Limit', align: 'right', cell: (t) => (t.spend_limit_usd === null ? <span className="text-muted">none</span> : formatUsd(t.spend_limit_usd)) },
    { key: 'spent', header: 'Spent', align: 'right', cell: (t) => formatUsd(t.spent_usd) },
    { key: 'used', header: 'Last used', className: 'whitespace-nowrap text-text-3', cell: (t) => (t.last_used_at ? formatAgo(t.last_used_at) : 'never') },
    {
      key: 'expires',
      header: 'Expires',
      className: 'whitespace-nowrap text-text-3',
      cell: (t) => (t.expired ? <span className="text-con">expired</span> : t.expires_at ? formatDateShort(t.expires_at) : 'never'),
    },
    {
      key: 'revoke',
      header: <span className="sr-only">Revoke</span>,
      align: 'right',
      cell: (t) => (
        <Button variant="ghost" size="sm" onClick={() => setTarget(t)}>
          Revoke
        </Button>
      ),
    },
  ];
  return (
    <Panel
      title="API tokens"
      aside={
        tokens.length > 1 && (
          <button type="button" className="cursor-pointer font-semibold text-con hover:underline" onClick={() => setTarget('all')}>
            Revoke all
          </button>
        )
      }
    >
      <DataTable caption="API tokens" columns={columns} rows={tokens} rowKey={(t) => t.id} empty="No API tokens." />
      <ActionDialog
        open={target !== null}
        title={target === 'all' ? 'Revoke every API token?' : `Revoke “${target?.name ?? ''}”?`}
        body="Scripts and agents using it get 401 at once; the user can make a new token."
        confirmLabel="Revoke"
        danger
        onClose={() => setTarget(null)}
        onSubmit={async (reason) => {
          const revoked = await revokeUserTokens(userId, reason, target === 'all' || !target ? undefined : target.id);
          toast.success(`${revoked} token${revoked === 1 ? '' : 's'} revoked`);
          onChanged();
        }}
      />
    </Panel>
  );
};

/** A page of an account's rows loaded on its own (the ledger, the debates); `version` reloads it. */
const usePaged = <T,>(fetchPage: (userId: string, offset: number, limit: number) => Promise<Page<T>>, userId: string, version: number, limit: number) => {
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<{ key: string; page: Page<T> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = `${userId}:${version}:${offset}`;
  useEffect(() => {
    let cancelled = false;
    fetchPage(userId, offset, limit)
      .then((page) => {
        if (!cancelled) {
          setResult({ key: `${userId}:${version}:${offset}`, page });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPage, userId, version, offset, limit]);
  return { offset, setOffset, page: result?.page ?? null, loading: result?.key !== key, error };
};

const LEDGER_PAGE = 50;

export const LedgerPanel = ({ userId, version }: { userId: string; version: number }) => {
  const { offset, setOffset, page, loading, error } = usePaged(getUserLedger, userId, version, LEDGER_PAGE);
  const columns: Column<AdminLedgerRow>[] = [
    { key: 'when', header: 'When', className: 'whitespace-nowrap text-text-3', cell: (t) => formatTime(t.created_at) },
    { key: 'type', header: 'Type', className: 'whitespace-nowrap text-text-3', cell: (t) => CATEGORY_LABELS[t.category] ?? t.kind },
    {
      key: 'title',
      header: 'Description',
      cell: (t) => (
        <span className="flex min-w-0 max-w-[340px] flex-col">
          <span className="truncate text-text-2" title={t.title}>
            {t.title}
          </span>
          {(t.reason || t.provider_ref) && (
            <span className="truncate text-[11px] text-muted" title={t.provider_ref ?? undefined}>
              {t.reason ? `reason: ${t.reason}` : t.provider_ref}
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'amount',
      header: 'Amount',
      align: 'right',
      cell: (t) => <span className={`font-mono ${t.amount_usd > 0 ? 'text-ok' : 'text-text'}`}>{formatSigned(t.amount_usd)}</span>,
    },
    { key: 'balance', header: 'Balance', align: 'right', className: 'font-mono text-text-3', cell: (t) => formatUsd(t.balance_after_usd) },
  ];
  return (
    <Panel title="Ledger" aside={page ? `${page.total} ${page.total === 1 ? 'row' : 'rows'}` : undefined}>
      {error && <ErrorBox className="m-4">{error}</ErrorBox>}
      {!page && !error && <Spinner className="m-4 size-5" />}
      {page && (
        <>
          <DataTable caption="Ledger" columns={columns} rows={page.rows} rowKey={(t) => t.id} loading={loading} empty="No ledger rows." />
          <Pager offset={offset} limit={LEDGER_PAGE} total={page.total} disabled={loading} onChange={setOffset} />
        </>
      )}
    </Panel>
  );
};

const DEBATE_PAGE = 20;

const debateLink = (d: AdminUserDebate) => d.url ?? `/api/admin/db/debate/details/${d.id}`;

export const DebatesPanel = ({ userId, version }: { userId: string; version: number }) => {
  const { offset, setOffset, page, loading, error } = usePaged(getUserDebates, userId, version, DEBATE_PAGE);
  const columns: Column<AdminUserDebate>[] = [
    {
      key: 'title',
      header: 'Debate',
      cell: (d) => (
        <span className="flex min-w-0 max-w-[360px] flex-col">
          <a href={debateLink(d)} {...(d.url ? { target: '_blank', rel: 'noreferrer' } : {})} className="truncate font-semibold text-text-2 hover:text-text hover:underline" title={d.title}>
            {d.title}
          </a>
          <span className="truncate text-[11px] text-muted" title={d.error ?? undefined}>
            {[d.is_public ? 'public' : 'private', d.moderation_status !== 'none' && d.moderation_status, d.own_key && 'own key', d.via_token && 'API token', d.media_status !== 'none' && `audio ${d.media_status}`]
              .filter(Boolean)
              .join(' · ')}
            {d.error && <span className="text-con"> · {d.error}</span>}
          </span>
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      className: 'whitespace-nowrap',
      cell: (d) => <span style={{ color: STATUS_COLORS[d.status as DebateStatus] ?? undefined }}>{STATUS_LABELS[d.status as DebateStatus] ?? d.status}</span>,
    },
    {
      key: 'models',
      header: 'Models',
      cell: (d) => (
        <span className="flex items-center gap-1" title={d.models.join(', ')}>
          {d.models.map((m, i) => (
            <ModelIcon key={`${m}-${i}`} modelId={m} size={14} />
          ))}
        </span>
      ),
    },
    { key: 'created', header: 'Created', className: 'whitespace-nowrap text-text-3', cell: (d) => formatDateShort(d.created_at) },
    { key: 'charged', header: 'Charged', align: 'right', cell: (d) => formatUsd(d.charged) },
    { key: 'reach', header: 'Likes · votes · views', align: 'right', className: 'whitespace-nowrap text-text-3', cell: (d) => `${d.likes} · ${d.votes} · ${d.views}` },
  ];
  return (
    <Panel title="Debates" aside={page ? `${page.total} in all, drafts included` : undefined}>
      {error && <ErrorBox className="m-4">{error}</ErrorBox>}
      {!page && !error && <Spinner className="m-4 size-5" />}
      {page && (
        <>
          <DataTable caption="Debates" columns={columns} rows={page.rows} rowKey={(d) => d.id} loading={loading} empty="No debates." />
          <Pager offset={offset} limit={DEBATE_PAGE} total={page.total} disabled={loading} onChange={setOffset} />
        </>
      )}
    </Panel>
  );
};

/** "amount_usd 5 · kind bonus" from an audit entry's after-state. */
const describe = (entry: AuditEntry) =>
  Object.entries(entry.after ?? {})
    .filter(([, v]) => v !== null && v !== '' && typeof v !== 'object')
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${String(v)}`)
    .join(' · ');

export const AuditPanel = ({ userId, entries }: { userId: string; entries: AuditEntry[] }) => (
  <Panel title="Audit log" aside="last 50: about the account, and by it as an admin">
    {entries.length === 0 ? (
      <p className="px-4 py-4 text-sm text-muted">Nothing recorded.</p>
    ) : (
      <ul className="divide-y divide-line/70">
        {entries.map((e) => (
          <li key={e.id} className="grid gap-0.5 px-4 py-2.5 text-xs">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className={`font-mono font-semibold ${e.ok ? 'text-text-2' : 'text-con'}`}>{e.action}</span>
              {!e.ok && <span className="text-con">failed</span>}
              {e.target_id !== userId && e.target_type && <span className="text-muted">on {e.target_type}</span>}
              <span className="ml-auto whitespace-nowrap text-muted">{formatTime(e.created_at)}</span>
            </div>
            <div className="text-muted">
              by {e.actor_email ?? 'unknown'}
              {e.ip && ` · ${e.ip}`}
            </div>
            {e.reason && <div className="text-text-3">“{e.reason}”</div>}
            {describe(e) && <div className="truncate font-mono text-[11px] text-dim">{describe(e)}</div>}
          </li>
        ))}
      </ul>
    )}
  </Panel>
);
