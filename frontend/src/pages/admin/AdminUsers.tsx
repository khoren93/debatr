import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Download, KeyRound, Terminal } from 'lucide-react';
import { needsSudo } from '../../api/admin/client';
import type { AdminUserList, AdminUserRow, UserSort } from '../../api/admin/types';
import { exportUsers, listUsers, type UserListQuery } from '../../api/admin/users';
import { getErrorMessage } from '../../api/client';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { DataTable, Pager, type Column } from '../../components/admin/DataTable';
import { FilterBar } from '../../components/admin/FilterBar';
import { flag, nextOrder, pageOf, pick, pickKey, utcDaysBack, withChanges, type FilterSpec } from '../../components/admin/filters';
import { SudoDialog } from '../../components/admin/SudoDialog';
import { UserBadges } from '../../components/admin/users/UserBadges';
import { formatUsd } from '../../components/admin/helpers';
import { downloadBlob } from '../../components/debate/helpers';
import { Button, Card, ErrorBox, Spinner, useToast } from '../../components/ui';
import { formatAgo, formatDateShort } from '../../lib/format';

const PAGE = 50;
const SORTS: UserSort[] = ['created', 'last_seen', 'balance', 'topped_up', 'spent', 'debates', 'likes', 'email'];

// URL parameter → choices; '' is "any". `signed` becomes `created_from` (N days back).
const FILTERS: FilterSpec[] = [
  { key: 'status', label: 'Status', options: [{ value: '', label: 'Any status' }, { value: 'active', label: 'Active' }, { value: 'disabled', label: 'Disabled' }] },
  { key: 'balance', label: 'Balance', options: [{ value: '', label: 'Any balance' }, { value: 'positive', label: 'Has credits' }, { value: 'negative', label: 'Below zero' }] },
  { key: 'paid', label: 'Payments', options: [{ value: '', label: 'Paid or not' }, { value: 'true', label: 'Has topped up' }, { value: 'false', label: 'Never topped up' }] },
  { key: 'active_days', label: 'Last seen', options: [{ value: '', label: 'Seen any time' }, { value: '1', label: 'Seen today' }, { value: '7', label: 'Seen in 7 days' }, { value: '30', label: 'Seen in 30 days' }, { value: '90', label: 'Seen in 90 days' }] },
  { key: 'signed', label: 'Signed up', options: [{ value: '', label: 'Signed up any time' }, { value: '1', label: 'Signed up today' }, { value: '7', label: 'In the last 7 days' }, { value: '30', label: 'In the last 30 days' }, { value: '90', label: 'In the last 90 days' }, { value: '365', label: 'In the last year' }] },
  { key: 'own_key', label: 'OpenRouter key', options: [{ value: '', label: 'Any key' }, { value: 'true', label: 'Own OpenRouter key' }, { value: 'false', label: 'No own key' }] },
  { key: 'tokens', label: 'API tokens', options: [{ value: '', label: 'Any API use' }, { value: 'true', label: 'Has API tokens' }, { value: 'false', label: 'No API tokens' }] },
  { key: 'staff', label: 'Role', options: [{ value: '', label: 'Any role' }, { value: 'true', label: 'Console staff' }, { value: 'false', label: 'Not staff' }] },
];

/** The API query of the page's URL (unknown values are dropped, not sent). */
const toQuery = (params: URLSearchParams): UserListQuery => {
  const get = (key: string) => pickKey(params, FILTERS, key);
  const sort = SORTS.find((s) => s === params.get('sort')) ?? 'created';
  const page = pageOf(params);
  const signed = get('signed');
  return {
    q: params.get('q')?.trim() || undefined,
    status: (get('status') || undefined) as UserListQuery['status'],
    balance: (get('balance') || undefined) as UserListQuery['balance'],
    paid: flag(get('paid')),
    own_key: flag(get('own_key')),
    tokens: flag(get('tokens')),
    staff: flag(get('staff')),
    active_days: get('active_days') ? Number(get('active_days')) : undefined,
    created_from: signed ? utcDaysBack(Number(signed)) : undefined,
    sort,
    order: params.get('order') === 'asc' ? 'asc' : 'desc',
    limit: PAGE,
    offset: page * PAGE,
  };
};

const COLUMNS: Column<AdminUserRow>[] = [
  {
    key: 'account',
    header: 'Account',
    sort: 'email',
    cell: (u) => (
      <span className="flex min-w-0 max-w-[280px] flex-col">
        <span className="flex items-center gap-2">
          <span className="truncate font-semibold text-text">{u.display_name}</span>
          <UserBadges role={u.role} active={u.is_active} />
        </span>
        <span className="truncate text-xs text-muted">{u.email}</span>
      </span>
    ),
  },
  { key: 'created', header: 'Signed up', sort: 'created', className: 'whitespace-nowrap text-text-3', cell: (u) => formatDateShort(u.created_at) },
  {
    key: 'seen',
    header: 'Last seen',
    sort: 'last_seen',
    className: 'whitespace-nowrap text-text-3',
    cell: (u) => (u.last_seen_at ? <span title={new Date(u.last_seen_at).toLocaleString()}>{formatAgo(u.last_seen_at)}</span> : <span className="text-dim">never</span>),
  },
  {
    key: 'balance',
    header: 'Balance',
    sort: 'balance',
    align: 'right',
    cell: (u) => <span className={u.credits_usd < 0 ? 'font-semibold text-con' : 'text-text'}>{formatUsd(u.credits_usd)}</span>,
  },
  { key: 'topped', header: 'Topped up', sort: 'topped_up', align: 'right', className: 'text-text-3', cell: (u) => formatUsd(u.topped_up) },
  {
    key: 'spent',
    header: 'Spent',
    sort: 'spent',
    align: 'right',
    className: 'text-text-3',
    cell: (u) => (
      <span title={`models ${formatUsd(u.spent_by.models)} · voices ${formatUsd(u.spent_by.voices)} · pictures ${formatUsd(u.spent_by.pictures)}`}>{formatUsd(u.spent)}</span>
    ),
  },
  {
    key: 'debates',
    header: 'Debates',
    sort: 'debates',
    align: 'right',
    className: 'whitespace-nowrap',
    cell: (u) => (
      <span title={`${u.failed} failed · ${u.public} public`}>
        <span className="text-text">{u.debates}</span>
        {u.failed > 0 && <span className="ml-1.5 text-xs text-con">{u.failed} failed</span>}
      </span>
    ),
  },
  { key: 'likes', header: 'Likes', sort: 'likes', align: 'right', className: 'text-text-3', cell: (u) => (u.votes ? `${u.likes} · ${u.votes} votes` : u.likes) },
  {
    key: 'access',
    header: <span className="sr-only">Keys and tokens</span>,
    className: 'whitespace-nowrap text-muted',
    cell: (u) => (
      <span className="flex items-center justify-end gap-2">
        {u.own_key && <KeyRound className="size-3.5" aria-label="Own OpenRouter key" />}
        {u.tokens > 0 && (
          <span className="flex items-center gap-0.5 text-xs" title={`${u.tokens} API token${u.tokens === 1 ? '' : 's'}`}>
            <Terminal className="size-3.5" aria-label="API tokens" />
            {u.tokens}
          </span>
        )}
      </span>
    ),
  },
];

const AdminUsers = () => {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const key = params.toString();
  const query = toQuery(params);
  const [result, setResult] = useState<{ key: string; data: AdminUserList } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [askCode, setAskCode] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listUsers(toQuery(new URLSearchParams(key)))
      .then((data) => {
        if (!cancelled) {
          setResult({ key, data });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [key]);

  const update = (changes: Record<string, string>) => setParams(withChanges(params, changes), { replace: true });
  const sortBy = (sort: string) => update({ sort, order: nextOrder(query, sort, ['email']) });

  const download = async () => {
    setExporting(true);
    try {
      const { blob, name } = await exportUsers({ ...query, limit: undefined, offset: undefined });
      downloadBlob(blob, name);
    } catch (err) {
      if (needsSudo(err)) setAskCode(true);
      else toast.error(getErrorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  const filtered = FILTERS.some((f) => pick(params, f)) || Boolean(query.q);
  const data = result?.data;
  const loading = result?.key !== key;

  return (
    <Page>
      <PageTitle
        kicker="Admin console"
        title="Users"
        right={
          <Button variant="secondary" size="sm" icon={<Download className="size-4" />} loading={exporting} onClick={download}>
            Export CSV
          </Button>
        }
      />

      <div className="mt-6">
        <FilterBar
          params={params}
          filters={FILTERS}
          searchLabel="Search accounts"
          searchPlaceholder="Email, name or account id"
          onChange={update}
          onReset={() => setParams(new URLSearchParams(), { replace: true })}
        />
      </div>

      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      <Card padding="none" className="mt-4 overflow-hidden">
        {!data && !error ? (
          <div className="flex justify-center py-10">
            <Spinner className="size-6" />
          </div>
        ) : (
          data && (
            <>
              <DataTable
                caption="Accounts"
                columns={COLUMNS}
                rows={data.rows}
                rowKey={(u) => u.id}
                rowHref={(u) => `/admin/users/${u.id}`}
                sort={{ key: query.sort ?? 'created', order: query.order ?? 'desc' }}
                onSort={sortBy}
                loading={loading}
                empty={filtered ? 'No account matches these filters.' : 'No accounts yet.'}
              />
              <Pager offset={data.offset} limit={data.limit} total={data.total} disabled={loading} onChange={(offset) => update({ page: String(offset / PAGE) })} />
            </>
          )
        )}
      </Card>

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

export default AdminUsers;
