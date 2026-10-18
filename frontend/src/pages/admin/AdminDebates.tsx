import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { X } from 'lucide-react';
import { listDebates, type DebateListQuery } from '../../api/admin/debates';
import type { AdminDebateList, AdminDebateRow, DebateSort } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { DataTable, Pager, type Column } from '../../components/admin/DataTable';
import { FilterBar } from '../../components/admin/FilterBar';
import { DebateFlags, DebateStatusText, ModerationText } from '../../components/admin/debates/DebateBits';
import { flag, nextOrder, pageOf, pick, pickKey, utcDaysBack, withChanges, type FilterSpec } from '../../components/admin/filters';
import { formatUsd } from '../../components/admin/helpers';
import { Card, ErrorBox, ModelIcon, Spinner } from '../../components/ui';
import { formatDateShort, formatDuration, shortModelName } from '../../lib/format';

const PAGE = 50;
const SORTS: DebateSort[] = ['created', 'likes', 'views', 'cost', 'charged', 'turns'];

const FILTERS: FilterSpec[] = [
  {
    key: 'status',
    label: 'Status',
    options: [
      { value: '', label: 'Any status' },
      { value: 'active', label: 'Queued or running' },
      { value: 'completed', label: 'Completed' },
      { value: 'error', label: 'Failed' },
      { value: 'stopped', label: 'Stopped' },
      { value: 'draft', label: 'Draft' },
    ],
  },
  {
    key: 'moderation',
    label: 'Moderation',
    options: [
      { value: '', label: 'Any moderation' },
      { value: 'flagged', label: 'Flagged' },
      { value: 'approved', label: 'Approved' },
      { value: 'rejected', label: 'Rejected' },
      { value: 'none', label: 'Not checked' },
    ],
  },
  { key: 'public', label: 'Gallery', options: [{ value: '', label: 'Public or not' }, { value: 'true', label: 'Public' }, { value: 'false', label: 'Private' }] },
  {
    key: 'media',
    label: 'Audio',
    options: [
      { value: '', label: 'Any audio' },
      { value: 'ready', label: 'Audio ready' },
      { value: 'error', label: 'Audio failed' },
      { value: 'running', label: 'Audio building' },
      { value: 'none', label: 'No audio' },
    ],
  },
  { key: 'own_key', label: 'Key', options: [{ value: '', label: 'Any key' }, { value: 'false', label: 'System key' }, { value: 'true', label: "Owner's key" }] },
  { key: 'via_token', label: 'Started from', options: [{ value: '', label: 'Browser or API' }, { value: 'false', label: 'Browser' }, { value: 'true', label: 'API token' }] },
  {
    key: 'created',
    label: 'Created',
    options: [
      { value: '', label: 'Created any time' },
      { value: '1', label: 'Created today' },
      { value: '7', label: 'In the last 7 days' },
      { value: '30', label: 'In the last 30 days' },
      { value: '90', label: 'In the last 90 days' },
    ],
  },
];

const toQuery = (params: URLSearchParams): DebateListQuery => {
  const get = (key: string) => pickKey(params, FILTERS, key);
  const status = get('status');
  const created = get('created');
  return {
    q: params.get('q')?.trim() || undefined,
    status: status && status !== 'active' ? status : undefined,
    active: status === 'active' ? true : undefined,
    moderation: get('moderation') || undefined,
    media: get('media') || undefined,
    public: flag(get('public')),
    own_key: flag(get('own_key')),
    via_token: flag(get('via_token')),
    model: params.get('model') || undefined,
    user_id: params.get('user_id') || undefined,
    created_from: created ? utcDaysBack(Number(created)) : undefined,
    sort: SORTS.find((s) => s === params.get('sort')) ?? 'created',
    order: params.get('order') === 'asc' ? 'asc' : 'desc',
    limit: PAGE,
    offset: pageOf(params) * PAGE,
  };
};

const columns = (withMoney: boolean): Column<AdminDebateRow>[] => [
  {
    key: 'title',
    header: 'Debate',
    cell: (d) => (
      <span className="flex min-w-0 max-w-[340px] 2xl:max-w-[520px] flex-col">
        <span className="truncate font-semibold text-text" title={d.title}>
          {d.title}
        </span>
        <span className="truncate text-xs text-muted">{d.owner ? d.owner.email : 'no owner (legacy)'}</span>
      </span>
    ),
  },
  {
    key: 'status',
    header: 'Status',
    className: 'whitespace-nowrap',
    cell: (d) => (
      <span className="flex flex-col" title={d.error ?? undefined}>
        <DebateStatusText status={d.status} />
        {d.error && <span className="max-w-[180px] truncate text-[11px] text-con">{d.error}</span>}
      </span>
    ),
  },
  {
    key: 'models',
    header: 'Models',
    cell: (d) => (
      <span className="flex items-center gap-1" title={d.models.map(shortModelName).join(' vs ')}>
        {d.models.map((m, i) => (
          <ModelIcon key={`${m}-${i}`} modelId={m} size={14} />
        ))}
      </span>
    ),
  },
  { key: 'created', header: 'Created', sort: 'created', className: 'whitespace-nowrap text-text-3', cell: (d) => formatDateShort(d.created_at) },
  {
    key: 'length',
    header: 'Turns',
    sort: 'turns',
    align: 'right',
    className: 'whitespace-nowrap text-text-3',
    cell: (d) => (
      <span title="turns · run time">
        {d.turns}
        {d.duration_ms ? <span className="text-muted"> · {formatDuration(d.duration_ms)}</span> : null}
      </span>
    ),
  },
  ...(withMoney
    ? [
        { key: 'cost', header: 'Cost', sort: 'cost', align: 'right' as const, className: 'text-text-3', cell: (d: AdminDebateRow) => formatUsd(d.cost ?? 0) },
        { key: 'charged', header: 'Charged', sort: 'charged', align: 'right' as const, cell: (d: AdminDebateRow) => formatUsd(d.charged ?? 0) },
      ]
    : []),
  {
    key: 'gallery',
    header: 'Gallery',
    className: 'whitespace-nowrap',
    cell: (d) => (
      <span className="flex flex-col text-xs">
        <span className={d.is_public ? 'text-ok' : 'text-muted'}>{d.is_public ? 'public' : 'private'}</span>
        <ModerationText status={d.moderation_status} />
      </span>
    ),
  },
  { key: 'flags', header: <span className="sr-only">Key, API and audio</span>, cell: (d) => <DebateFlags debate={d} /> },
  { key: 'reach', header: 'Likes · votes · views', sort: 'likes', align: 'right', className: 'whitespace-nowrap text-text-3', cell: (d) => `${d.likes} · ${d.votes} · ${d.views}` },
];

const Chip = ({ label, onClear }: { label: string; onClear: () => void }) => (
  <span className="inline-flex items-center gap-1.5 rounded-full border border-line-2 bg-surface-2 py-1 pl-3 pr-1.5 text-xs text-text-2">
    {label}
    <button type="button" onClick={onClear} aria-label={`Clear ${label}`} className="cursor-pointer rounded-full p-0.5 text-muted hover:text-text">
      <X className="size-3.5" />
    </button>
  </span>
);

const AdminDebates = () => {
  const { me } = useAdminAuth();
  const [params, setParams] = useSearchParams();
  const key = params.toString();
  const query = toQuery(params);
  const [result, setResult] = useState<{ key: string; data: AdminDebateList } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listDebates(toQuery(new URLSearchParams(key)))
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
  const data = result?.data;
  const loading = result?.key !== key;
  const withMoney = Boolean(me?.permissions.includes('money'));
  const filtered = FILTERS.some((f) => pick(params, f)) || Boolean(query.q || query.model || query.user_id);
  const owner = data?.rows.find((r) => r.owner?.id === query.user_id)?.owner;

  return (
    <Page>
      <PageTitle kicker="Admin console" title="Debates" />
      <div className="mt-6">
        <FilterBar
          params={params}
          filters={FILTERS}
          searchLabel="Search debates"
          searchPlaceholder="Title, id or slug"
          onChange={update}
          onReset={() => setParams(new URLSearchParams(), { replace: true })}
        />
      </div>
      {(query.model || query.user_id) && (
        <div className="mt-3 flex flex-wrap gap-2">
          {query.model && <Chip label={`Model: ${shortModelName(query.model)}`} onClear={() => update({ model: '' })} />}
          {query.user_id && <Chip label={`Owner: ${owner?.email ?? query.user_id.slice(0, 8)}`} onClear={() => update({ user_id: '' })} />}
        </div>
      )}

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
                caption="Debates"
                columns={columns(withMoney)}
                rows={data.rows}
                rowKey={(d) => d.id}
                rowHref={(d) => `/admin/debates/${d.id}`}
                sort={{ key: query.sort ?? 'created', order: query.order ?? 'desc' }}
                onSort={(sort) => update({ sort, order: nextOrder(query, sort) })}
                loading={loading}
                empty={filtered ? 'No debate matches these filters.' : 'No debates yet.'}
              />
              <Pager offset={data.offset} limit={data.limit} total={data.total} disabled={loading} onChange={(offset) => update({ page: String(offset / PAGE) })} />
            </>
          )
        )}
      </Card>
    </Page>
  );
};

export default AdminDebates;
