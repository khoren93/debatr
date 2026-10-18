import { useState } from 'react';
import { Link } from 'react-router-dom';
import { getLimits, getRuns, recoverRun } from '../../../api/admin/system';
import type { FairShareUser, RunInfo } from '../../../api/admin/types';
import { Button, useToast } from '../../ui';
import { ActionDialog } from '../ActionDialog';
import { DataTable, type Column } from '../DataTable';
import { formatSpan, formatTime } from '../helpers';
import { useLoad } from '../useLoad';
import { Panel } from '../users/UserSections';
import { Figure, State, SystemSection } from './SystemBits';

const loadRuns = () => getRuns();
const loadLimits = () => getLimits();

/** Debates and audio builds in flight; a run without a worker can be queued again now. */
export const RunsSection = () => {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad(loadRuns, 15_000);
  const [target, setTarget] = useState<RunInfo | null>(null);

  const columns: Column<RunInfo>[] = [
    {
      key: 'debate',
      header: 'Run',
      cell: (r) => (
        <span className="flex min-w-0 max-w-[340px] 2xl:max-w-[520px] flex-col">
          <Link to={`/admin/debates/${r.debate_id}`} className="truncate font-semibold text-text-2 hover:text-text hover:underline">
            {r.title}
          </Link>
          <span className="truncate text-[11px] text-muted">
            {r.kind === 'media' ? 'audio build' : 'debate'} · {r.owner_email ?? 'no owner'}
          </span>
        </span>
      ),
    },
    { key: 'step', header: 'Step', className: 'text-text-3', cell: (r) => `${r.status} · ${r.step}` },
    { key: 'age', header: 'For', className: 'whitespace-nowrap text-text-3', cell: (r) => formatSpan(r.age_seconds) },
    {
      key: 'worker',
      header: 'Worker',
      className: 'whitespace-nowrap',
      cell: (r) =>
        r.heartbeat ? <State tone="ok">working</State> : r.waiting ? <State tone="warn">job waiting</State> : <State tone={r.stuck ? 'bad' : 'warn'}>{r.stuck ? 'none, stuck' : 'none yet'}</State>,
    },
    { key: 'attempts', header: 'Recovered', align: 'right', className: 'text-text-3', cell: (r) => (r.attempts ? `${r.attempts}×` : '—') },
    {
      key: 'recover',
      header: <span className="sr-only">Recover</span>,
      align: 'right',
      cell: (r) =>
        !r.heartbeat && !r.waiting ? (
          <Button variant="secondary" size="sm" onClick={() => setTarget(r)}>
            Recover now
          </Button>
        ) : null,
    },
  ];

  const stuck = data?.filter((r) => r.stuck).length ?? 0;

  return (
    <SystemSection id="runs" title="Runs in flight" aside={data ? `${data.length} going${stuck ? ` · ${stuck} stuck` : ''}` : undefined} loading={loading} error={error} onRefresh={() => reload()}>
      {data && (
        <Panel title="Queued or running">
          <DataTable caption="Runs in flight" columns={columns} rows={data} rowKey={(r) => `${r.kind}:${r.debate_id}`} empty="Nothing is running." />
        </Panel>
      )}
      <ActionDialog
        open={target !== null}
        title="Recover this run now?"
        body="It has no worker and no job waiting. It is queued again from its first missing step, as the watchdog would after two checks; after too many attempts it fails instead."
        confirmLabel="Recover"
        autoFocusReason
        onClose={() => setTarget(null)}
        onSubmit={async (reason) => {
          if (!target) return;
          toast.success((await recoverRun(target.debate_id, target.kind, reason)).message);
          reload();
        }}
      />
    </SystemSection>
  );
};

const fairColumns = (now: boolean): Column<FairShareUser>[] => [
  {
    key: 'user',
    header: 'Account',
    cell: (u) => (
      <Link to={`/admin/users/${u.user_id}`} className="text-text-2 hover:underline">
        {u.email ?? u.user_id.slice(0, 8)}
      </Link>
    ),
  },
  { key: 'kind', header: 'Of', className: 'text-text-3', cell: (u) => (u.kind === 'media' ? 'audio builds' : 'debates') },
  now
    ? { key: 'active', header: 'Running', align: 'right', cell: (u) => u.active ?? '—' }
    : { key: 'refusals', header: 'Refused', align: 'right', cell: (u) => `${u.refusals}×` },
  ...(now ? [] : [{ key: 'last', header: 'Last', className: 'whitespace-nowrap text-text-3', cell: (u: FairShareUser) => (u.last_refused_at ? formatTime(u.last_refused_at) : '—') }]),
];

/** The shared free-model quota and the per-account fair share of the workers. */
export const LimitsSection = () => {
  const { data, loading, error, reload } = useLoad(loadLimits, 30_000);
  const minuteFull = data && data.free_per_minute > 0 && data.free_used_this_minute >= data.free_per_minute;
  const dayShare = data ? data.free_requests_24h / data.free_daily_cap : 0;
  return (
    <SystemSection id="limits" title="Limits" loading={loading} error={error} onRefresh={() => reload()}>
      {data && (
        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Figure
              label="Free-model slots this minute"
              value={data.free_per_minute > 0 ? `${Math.min(data.free_used_this_minute, data.free_per_minute)} / ${data.free_per_minute}` : 'no limit'}
              tone={minuteFull ? 'warn' : undefined}
              hint={minuteFull ? 'full: turns wait for the next minute' : 'system key, shared by every user'}
            />
            <Figure
              label=":free requests in 24 h"
              value={`${data.free_requests_24h} / ${data.free_daily_cap}`}
              tone={dayShare >= 1 ? 'bad' : dayShare >= 0.8 ? 'warn' : undefined}
              hint={data.free_daily_cap < 1000 ? 'OpenRouter allows 1000 a day after $10 of credits' : "OpenRouter's daily cap"}
            />
            <Figure label="Rate-limited in 24 h" value={data.free_rate_limited_24h} tone={data.free_rate_limited_24h ? 'warn' : undefined} hint="429s from free models" />
            <Figure
              label="Fair share per account"
              value={`${data.max_debates_per_user || '∞'} · ${data.max_media_per_user || '∞'}`}
              hint={`debates · audio builds at a time; ${data.debate_create_rate_limit || '∞'} new debates an hour per IP`}
            />
          </div>
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Panel title="At the limit now">
              <DataTable caption="Accounts at the limit" columns={fairColumns(true)} rows={data.at_limit_now} rowKey={(u) => `${u.kind}:${u.user_id}`} empty="Nobody is at the limit." />
            </Panel>
            <Panel title="Refused in 24 h">
              <DataTable caption="Refused accounts" columns={fairColumns(false)} rows={data.refused_24h} rowKey={(u) => `${u.kind}:${u.user_id}`} empty="No refusals." />
            </Panel>
          </div>
        </div>
      )}
    </SystemSection>
  );
};
