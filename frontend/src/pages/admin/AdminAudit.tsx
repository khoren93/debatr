import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { getAuditFacets, getSecuritySummary, listAudit } from '../../api/admin/audit';
import type { AuditEntry, AuditFacets, AuditPage, AuditQuery, AuditTab, FacetCount, SecuritySummary } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { Pager } from '../../components/admin/DataTable';
import { FilterBar, FilterChip } from '../../components/admin/FilterBar';
import { flag, pageOf, utcDaysBack, withChanges, type FilterSpec } from '../../components/admin/filters';
import { StatTile } from '../../components/admin/StatTile';
import { describeAgent, formatTime } from '../../components/admin/helpers';
import { Card, ErrorBox, Segmented, Spinner } from '../../components/ui';

const PAGE = 50;
const TABS: { value: AuditTab; label: string }[] = [
  { value: 'all', label: 'All events' },
  { value: 'security', label: 'Security' },
];

const count = (facet: FacetCount) => `${facet.value} (${facet.count.toLocaleString()})`;

/** Dropdown filters; the action and actor choices come from the log itself. */
const filtersOf = (facets: AuditFacets | null): FilterSpec[] => {
  const actions = facets?.actions ?? [];
  const groups = new Map<string, number>();
  for (const a of actions) {
    const group = `${a.value.split('.')[0]}.`;
    groups.set(group, (groups.get(group) ?? 0) + a.count);
  }
  return [
    {
      key: 'action',
      label: 'Action',
      options: [
        { value: '', label: 'Any action' },
        ...[...groups.entries()].sort().map(([group, n]) => ({ value: group, label: `${group}* (${n.toLocaleString()})` })),
        ...actions.map((a) => ({ value: a.value, label: count(a) })),
      ],
    },
    { key: 'actor', label: 'Who', options: [{ value: '', label: 'Anyone' }, ...(facets?.actors ?? []).map((a) => ({ value: a.value, label: count(a) }))] },
    { key: 'ok', label: 'Outcome', options: [{ value: '', label: 'Any outcome' }, { value: 'true', label: 'Succeeded' }, { value: 'false', label: 'Failed or refused' }] },
    {
      key: 'days',
      label: 'Period',
      options: [{ value: '', label: 'Any time' }, { value: '1', label: 'Today' }, { value: '7', label: 'Last 7 days' }, { value: '30', label: 'Last 30 days' }, { value: '90', label: 'Last 90 days' }],
    },
  ];
};

const DAYS = new Set(['1', '7', '30', '90']);

/** The API query of the page's URL. Action and actor are taken as they are (links from cards
 * and rows set them before the dropdowns know their values). */
const toQuery = (params: URLSearchParams): AuditQuery => {
  const days = params.get('days') ?? '';
  return {
    tab: params.get('tab') === 'security' ? 'security' : 'all',
    q: params.get('q')?.trim() || undefined,
    action: params.get('action')?.trim() || undefined,
    actor: params.get('actor')?.trim() || undefined,
    ok: flag(params.get('ok') ?? ''),
    target_type: params.get('target_type') || undefined,
    target_id: params.get('target_id') || undefined,
    created_from: DAYS.has(days) ? utcDaysBack(Number(days)) : undefined,
    limit: PAGE,
    offset: pageOf(params) * PAGE,
  };
};

/** Where a target opens in the console (or nowhere). */
const targetHref = (entry: AuditEntry): string | null => {
  const id = entry.target_id;
  if (!id) return entry.target_type === 'trending_batch' ? '/admin/trending' : null;
  switch (entry.target_type) {
    case 'user':
      return `/admin/users/${id}`;
    case 'debate':
      return `/admin/debates/${id}`;
    case 'trending_topic':
    case 'trending_batch':
      return '/admin/trending';
    case 'setting':
      return '/admin/settings';
    default:
      return null;
  }
};

/** Ids of rows are long: the first 8 characters of a UUID tell them apart. */
const shortId = (id: string | null) => (id && /^[0-9a-f-]{32,36}$/i.test(id) ? id.slice(0, 8) : (id ?? ''));

const show = (value: unknown): string => {
  if (value === undefined) return '—';
  if (value === null) return 'null';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

/** Field by field: what it was and what it became (only "after" for most actions). */
const Changes = ({ entry }: { entry: AuditEntry }) => {
  const before = entry.before ?? {};
  const after = entry.after ?? {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  if (keys.length === 0) return <p className="text-xs text-muted">No values recorded.</p>;
  const both = entry.before !== null && entry.after !== null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted">
            <th scope="col" className="py-1 pr-3 font-medium">
              Field
            </th>
            {entry.before !== null && (
              <th scope="col" className="py-1 pr-3 font-medium">
                Before
              </th>
            )}
            {entry.after !== null && (
              <th scope="col" className="py-1 font-medium">
                After
              </th>
            )}
          </tr>
        </thead>
        <tbody className="font-mono">
          {keys.map((key) => {
            const changed = both && show(before[key]) !== show(after[key]);
            return (
              <tr key={key} className="border-t border-line/60 align-top">
                <td className="py-1.5 pr-3 text-text-3">{key}</td>
                {entry.before !== null && <td className={`max-w-[420px] break-all py-1.5 pr-3 ${changed ? 'text-con' : 'text-text-2'}`}>{show(before[key])}</td>}
                {entry.after !== null && <td className={`max-w-[420px] break-all py-1.5 ${changed ? 'text-pro' : 'text-text-2'}`}>{show(after[key])}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

const EntryRow = ({ entry, onFilter }: { entry: AuditEntry; onFilter: (changes: Record<string, string>) => void }) => {
  const [open, setOpen] = useState(false);
  const href = targetHref(entry);
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <li className="px-4 py-2.5 text-xs">
      <div className="flex items-start gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label={open ? 'Hide details' : 'Show details'} className="mt-0.5 cursor-pointer rounded p-0.5 text-muted hover:text-text">
          <Icon className="size-3.5" />
        </button>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <button type="button" onClick={() => onFilter({ action: entry.action })} className={`cursor-pointer font-mono font-semibold hover:underline ${entry.ok ? 'text-text-2' : 'text-con'}`} title="Only this action">
              {entry.action}
            </button>
            {!entry.ok && <span className="text-con">failed</span>}
            {entry.target_type && (
              <span className="text-muted">
                on{' '}
                {href ? (
                  <Link to={href} className="text-text-3 hover:text-text hover:underline">
                    {entry.target_type} {shortId(entry.target_id)}
                  </Link>
                ) : (
                  <span className="text-text-3">
                    {entry.target_type} {shortId(entry.target_id)}
                  </span>
                )}
              </span>
            )}
            <span className="ml-auto whitespace-nowrap text-muted" title={new Date(entry.created_at).toLocaleString()}>
              {formatTime(entry.created_at)}
            </span>
          </div>
          <div className="text-muted">
            by{' '}
            {entry.actor_email ? (
              <button type="button" onClick={() => onFilter({ actor: entry.actor_email ?? '' })} className="cursor-pointer text-text-3 hover:text-text hover:underline" title="Only this person">
                {entry.actor_email}
              </button>
            ) : (
              'unknown'
            )}
            {entry.ip && ` · ${entry.ip}`}
          </div>
          {entry.reason && <div className="text-text-3">“{entry.reason}”</div>}
          {open && (
            <div className="mt-2 grid gap-2 rounded-[10px] border border-line bg-ink-2 p-3">
              <Changes entry={entry} />
              <div className="grid gap-0.5 text-[11px] text-muted">
                {entry.user_agent && <div title={entry.user_agent}>{describeAgent(entry.user_agent)}</div>}
                <div className="font-mono">entry {entry.id}</div>
                {entry.target_id && (
                  <button type="button" onClick={() => onFilter({ target_type: entry.target_type ?? '', target_id: entry.target_id ?? '' })} className="w-fit cursor-pointer text-left hover:text-text hover:underline">
                    Everything about {entry.target_type} {entry.target_id}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </li>
  );
};

const SecurityTiles = ({ summary }: { summary: SecuritySummary }) => (
  <div className="grid gap-3">
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      <StatTile label="Sign-ins" value={summary.sign_ins.toLocaleString()} hint="last 7 days" />
      <StatTile label="Wrong passwords and codes" value={summary.failures.toLocaleString()} hint="last 7 days" />
      <StatTile label="Lock-outs" value={summary.locks.toLocaleString()} hint="5 wrong codes in 15 min" />
      <StatTile label="Recovery codes used" value={summary.recovery_codes_used.toLocaleString()} hint="last 7 days" />
      <StatTile label="Addresses" value={summary.addresses.toLocaleString()} hint="distinct IPs that tried" />
    </div>
    {summary.last_failure && (
      <p className="text-xs text-muted">
        Last failure: <span className="font-mono text-con">{summary.last_failure.action}</span> by {summary.last_failure.actor_email ?? 'unknown'}
        {summary.last_failure.ip && ` from ${summary.last_failure.ip}`}, {formatTime(summary.last_failure.created_at)}
      </p>
    )}
  </div>
);

const AdminAudit = () => {
  const [params, setParams] = useSearchParams();
  const [facets, setFacets] = useState<AuditFacets | null>(null);
  const [summary, setSummary] = useState<SecuritySummary | null>(null);
  const [result, setResult] = useState<{ key: string; data: AuditPage } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const filters = filtersOf(facets);
  const key = params.toString();
  const query = toQuery(params);
  const security = query.tab === 'security';

  useEffect(() => {
    let cancelled = false;
    getAuditFacets()
      .then((data) => {
        if (!cancelled) setFacets(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!security) return;
    let cancelled = false;
    getSecuritySummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [security]);

  useEffect(() => {
    let cancelled = false;
    listAudit(toQuery(new URLSearchParams(key)))
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

  return (
    <Page>
      <PageTitle kicker="Admin console" title="Audit log" right={<Segmented size="sm" options={TABS} value={query.tab ?? 'all'} onChange={(tab) => update({ tab: tab === 'all' ? '' : tab })} />} />
      <p className="mt-2 max-w-2xl text-sm text-muted">
        Every console action and security event, newest first. The log only grows: nothing here can be changed or deleted.
      </p>
      {security && summary && (
        <div className="mt-6">
          <SecurityTiles summary={summary} />
        </div>
      )}
      <div className="mt-6">
        <FilterBar
          key={facets ? 'facets' : 'plain'}
          params={params}
          filters={filters}
          searchLabel="Search the audit log"
          searchPlaceholder="Action, email, target id, IP or reason"
          onChange={update}
          onReset={() => setParams(security ? new URLSearchParams({ tab: 'security' }) : new URLSearchParams(), { replace: true })}
        />
      </div>
      {(query.target_id || query.target_type) && (
        <div className="mt-3 flex flex-wrap gap-2">
          <FilterChip label={`Target: ${query.target_type ?? ''} ${shortId(query.target_id ?? null)}`.trim()} onClear={() => update({ target_type: '', target_id: '' })} />
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
              {data.rows.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm text-muted">Nothing recorded matches.</p>
              ) : (
                <ul className={`divide-y divide-line/70 transition-opacity ${loading ? 'opacity-60' : ''}`}>
                  {data.rows.map((entry) => (
                    <EntryRow key={entry.id} entry={entry} onFilter={update} />
                  ))}
                </ul>
              )}
              <Pager offset={data.offset} limit={data.limit} total={data.total} disabled={loading} onChange={(offset) => update({ page: String(offset / PAGE) })} />
            </>
          )
        )}
      </Card>
    </Page>
  );
};

export default AdminAudit;
