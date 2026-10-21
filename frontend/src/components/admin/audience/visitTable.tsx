import type { VisitRow } from '../../../api/admin/types';
import { RelativeDate } from '../../ui';
import type { Column } from '../DataTable';
import { DeviceIcon, PlaceText, SourceText } from './VisitBits';
import { duration } from './format';

/** Columns of a visits table (the list, live now, an account's visits). */
export const visitColumns = ({ who = true }: { who?: boolean } = {}): Column<VisitRow>[] => [
  {
    key: 'started',
    header: 'When',
    sort: 'started',
    className: 'whitespace-nowrap',
    cell: (v) => (
      <span className="flex flex-col">
        <RelativeDate iso={v.started_at} />
        <span className="text-[11px] text-muted">{duration(v.engaged_ms)} on the site</span>
      </span>
    ),
  },
  ...(who
    ? [
        {
          key: 'who',
          header: 'Who',
          cell: (v: VisitRow) => (
            <span className="flex min-w-0 flex-col">
              <span className="max-w-[220px] truncate text-text" title={v.user?.email}>
                {v.user ? v.user.email : 'Anonymous'}
                {v.staff && <span className="ml-1.5 rounded bg-surface-3 px-1 text-[10px] text-muted">staff</span>}
              </span>
              <span className="text-[11px] text-muted">
                {v.new_visitor ? 'new visitor' : 'returning'} · <span className="font-mono">{v.visitor_id.slice(0, 8)}</span>
              </span>
            </span>
          ),
        },
      ]
    : []),
  { key: 'where', header: 'Where', cell: (v) => <PlaceText visit={v} /> },
  { key: 'source', header: 'Came from', cell: (v) => <SourceText source={v.source} host={v.referrer_host} campaign={v.utm_campaign} /> },
  {
    key: 'path',
    header: 'Pages',
    cell: (v) => (
      <span className="flex min-w-0 flex-col">
        <span className="max-w-[240px] truncate font-mono text-[11px] text-text-2" title={`${v.landing} → ${v.exit_path}`}>
          {v.landing}
          {v.exit_path !== v.landing && <span className="text-muted"> → {v.exit_path}</span>}
        </span>
        <span className="text-[11px] text-muted">
          {v.pageviews} {v.pageviews === 1 ? 'page' : 'pages'}
          {v.actions ? ` · ${v.actions} ${v.actions === 1 ? 'action' : 'actions'}` : ''}
        </span>
      </span>
    ),
  },
  {
    key: 'device',
    header: 'Device',
    className: 'whitespace-nowrap',
    cell: (v) => (
      <span className="flex items-center gap-1.5 text-text-3">
        <DeviceIcon device={v.device} />
        {[v.browser, v.os].filter(Boolean).join(' · ') || v.device}
      </span>
    ),
  },
];
