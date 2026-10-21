import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { listVisits } from '../../api/admin/audience';
import type { OverviewPeriod, VisitList, VisitListQuery, VisitRow, VisitSort } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { DataTable, Pager, type Column } from '../../components/admin/DataTable';
import { FilterBar, FilterChip } from '../../components/admin/FilterBar';
import { ACTION_LABELS, countryName, flagOf } from '../../components/admin/audience/format';
import { visitColumns } from '../../components/admin/audience/visitTable';
import { SOURCE_LABELS } from '../../components/admin/charts/palette';
import { flag, nextOrder, pageOf, pick, pickKey, withChanges, type FilterSpec } from '../../components/admin/filters';
import { Card, ErrorBox, Spinner } from '../../components/ui';

const PAGE = 50;
const SORTS: VisitSort[] = ['started', 'engaged', 'pageviews', 'actions'];
const PERIODS: OverviewPeriod[] = ['24h', '7d', '30d', '90d', 'all'];

const FILTERS: FilterSpec[] = [
  {
    key: 'period',
    label: 'Period',
    options: [
      { value: '', label: 'Last 7 days' },
      { value: '24h', label: 'Last 24 hours' },
      { value: '30d', label: 'Last 30 days' },
      { value: '90d', label: 'Last 90 days' },
      { value: 'all', label: 'All time' },
    ],
  },
  { key: 'source', label: 'Source', options: [{ value: '', label: 'Any source' }, ...Object.entries(SOURCE_LABELS).map(([value, label]) => ({ value, label }))] },
  {
    key: 'device',
    label: 'Device',
    options: [
      { value: '', label: 'Any device' },
      { value: 'desktop', label: 'Desktop' },
      { value: 'mobile', label: 'Phone' },
      { value: 'tablet', label: 'Tablet' },
    ],
  },
  { key: 'signed_in', label: 'Account', options: [{ value: '', label: 'Signed in or not' }, { value: 'true', label: 'Signed in' }, { value: 'false', label: 'Anonymous' }] },
  { key: 'new_visitor', label: 'Visitor', options: [{ value: '', label: 'New or returning' }, { value: 'true', label: 'New visitors' }, { value: 'false', label: 'Returning' }] },
  { key: 'action', label: 'Action', options: [{ value: '', label: 'Any action' }, ...Object.entries(ACTION_LABELS).map(([value, label]) => ({ value, label }))] },
  { key: 'staff', label: 'Staff', options: [{ value: '', label: 'Without staff' }, { value: 'true', label: 'With staff' }] },
];

const toQuery = (params: URLSearchParams): VisitListQuery => {
  const get = (key: string) => pickKey(params, FILTERS, key);
  const country = params.get('country')?.trim().toUpperCase();
  const device = get('device');
  return {
    period: PERIODS.find((p) => p === get('period')) ?? '7d',
    q: params.get('q')?.trim() || undefined,
    source: get('source') || undefined,
    country: country && /^[A-Z]{2}$/.test(country) ? country : undefined,
    device: device === 'desktop' || device === 'mobile' || device === 'tablet' ? device : undefined,
    signed_in: flag(get('signed_in')),
    new_visitor: flag(get('new_visitor')),
    action: get('action') || undefined,
    staff: get('staff') === 'true' || undefined,
    sort: SORTS.find((s) => s === params.get('sort')) ?? 'started',
    order: params.get('order') === 'asc' ? 'asc' : 'desc',
    limit: PAGE,
    offset: pageOf(params) * PAGE,
  };
};

/** Every visit of a period, filtered and searched (`/admin/audience/visits`, filters in the URL). */
const AdminVisits = () => {
  const [params, setParams] = useSearchParams();
  const key = params.toString();
  const query = toQuery(params);
  const [result, setResult] = useState<{ key: string; data: VisitList } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listVisits(toQuery(new URLSearchParams(key)))
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
  const filtered = FILTERS.some((f) => pick(params, f)) || Boolean(query.q || query.country);

  return (
    <Page>
      <PageTitle
        kicker="Audience"
        title="Visits"
        right={
          <Link to="/admin/audience" className="text-sm text-accent hover:text-accent-hover">
            ← Audience
          </Link>
        }
      />
      <div className="mt-6">
        <FilterBar
          params={params}
          filters={FILTERS}
          searchLabel="Search visits"
          searchPlaceholder="IP, email, city, page, site or an id"
          onChange={update}
          onReset={() => setParams(new URLSearchParams(), { replace: true })}
        />
      </div>
      {query.country && (
        <div className="mt-3 flex flex-wrap gap-2">
          <FilterChip label={`Country: ${flagOf(query.country)} ${countryName(query.country)}`} onClear={() => update({ country: '' })} />
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
                caption="Visits"
                columns={visitColumns().map((c): Column<VisitRow> => (c.key === 'path' ? { ...c, sort: 'pageviews' } : c))}
                rows={data.items}
                rowKey={(v) => v.id}
                rowHref={(v) => `/admin/audience/visits/${v.id}`}
                sort={{ key: query.sort ?? 'started', order: query.order ?? 'desc' }}
                onSort={(sort) => update({ sort, order: nextOrder(query, sort) })}
                loading={loading}
                empty={filtered ? 'No visit matches these filters.' : 'No visits in this period.'}
              />
              <Pager offset={query.offset ?? 0} limit={PAGE} total={data.total} disabled={loading} onChange={(offset) => update({ page: String(offset / PAGE) })} />
            </>
          )
        )}
      </Card>
    </Page>
  );
};

export default AdminVisits;
