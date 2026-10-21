import { useCallback } from 'react';
import { Link } from 'react-router';
import { getUserVisits } from '../../../api/admin/audience';
import { formatCount } from '../../../lib/format';
import { ErrorBox, Spinner } from '../../ui';
import { DataTable } from '../DataTable';
import { SourceText } from '../audience/VisitBits';
import { visitColumns } from '../audience/visitTable';
import { duration, flagOf, placeText } from '../audience/format';
import { formatTime } from '../helpers';
import { useLoad } from '../useLoad';
import { Panel } from './UserSections';

/** The account's visits (with its browsers' visits before it signed in), where it first came
 *  from, its addresses and the other accounts seen on them. */
export const UserVisitsPanel = ({ userId }: { userId: string }) => {
  const load = useCallback(() => getUserVisits(userId), [userId]);
  const { data, error } = useLoad(load);
  return (
    <Panel
      title="Visits"
      aside={
        data && (
          <span className="flex items-center gap-3">
            {formatCount(data.total)} {data.total === 1 ? 'visit' : 'visits'} · {duration(data.engaged_ms)} on the site · {formatCount(data.pageviews)} {data.pageviews === 1 ? 'page' : 'pages'}
            <Link to={`/admin/audience/visits?period=all&q=${userId}`} className="font-semibold hover:text-text">
              All visits
            </Link>
          </span>
        )
      }
    >
      {error && <ErrorBox className="m-3">{error}</ErrorBox>}
      {!data && !error && (
        <div className="flex justify-center py-6">
          <Spinner className="size-5" />
        </div>
      )}
      {data && data.total === 0 && <p className="px-4 py-4 text-sm text-muted">No visit recorded (visits are kept since the Audience page exists).</p>}
      {data && data.total > 0 && (
        <>
          <div className="grid gap-4 border-b border-line px-4 py-3 text-xs md:grid-cols-[1fr_1.4fr_1.4fr]">
            <div className="min-w-0">
              <div className="text-muted">First came from</div>
              {data.first && (
                <div className="mt-1 grid gap-0.5">
                  <SourceText source={data.first.source} host={data.first.referrer_host} campaign={data.first.utm_campaign} />
                  <span className="text-muted">
                    {formatTime(data.first.started_at)} · landed on <span className="font-mono">{data.first.landing}</span>
                  </span>
                </div>
              )}
            </div>
            <div className="min-w-0">
              <div className="text-muted">Addresses</div>
              <ul className="mt-1 grid gap-0.5">
                {data.addresses.slice(0, 6).map((a) => (
                  <li key={a.ip} className="flex justify-between gap-2">
                    <span className="min-w-0 truncate" title={placeText(a)}>
                      <span className="font-mono text-text-2">{a.ip}</span> {flagOf(a.country)} {placeText(a)}
                    </span>
                    <span className="shrink-0 text-muted">{a.visits}×</span>
                  </li>
                ))}
                {data.addresses.length === 0 && <li className="text-muted">None kept (cleared after the retention days).</li>}
              </ul>
            </div>
            <div className="min-w-0">
              <div className="text-muted">Other accounts on these addresses</div>
              <ul className="mt-1 grid gap-0.5">
                {data.shared.slice(0, 6).map((s) => (
                  <li key={`${s.ip}-${s.user.id}`} className="flex justify-between gap-2">
                    <Link to={`/admin/users/${s.user.id}`} className="min-w-0 truncate text-con hover:text-text">
                      {s.user.email}
                    </Link>
                    <span className="shrink-0 font-mono text-muted">{s.ip}</span>
                  </li>
                ))}
                {data.shared.length === 0 && <li className="text-muted">None.</li>}
              </ul>
            </div>
          </div>
          <DataTable caption="Visits of the account" columns={visitColumns({ who: false })} rows={data.visits} rowKey={(v) => v.id} rowHref={(v) => `/admin/audience/visits/${v.id}`} />
        </>
      )}
    </Panel>
  );
};
