import { useState } from 'react';
import { Link } from 'react-router-dom';
import { failedJobAction, getQueues } from '../../../api/admin/system';
import type { JobSummary, WorkerInfo } from '../../../api/admin/types';
import { Button, useToast } from '../../ui';
import { ActionDialog } from '../ActionDialog';
import { DataTable, type Column } from '../DataTable';
import { formatSpan, formatTime, secondsSince } from '../helpers';
import { useLoad } from '../useLoad';
import { Panel } from '../users/UserSections';
import { Figure, State, SystemSection } from './SystemBits';

const loadQueues = () => getQueues();

const STATUS_TONES: Record<string, string> = { finished: 'text-ok', failed: 'text-con', started: 'text-host', queued: 'text-text-3' };

const JobRef = ({ job }: { job: JobSummary }) => (
  <span className="flex min-w-0 flex-col">
    <span className="font-mono text-[12px] text-text-2">{job.func}</span>
    {job.debate_id && (
      <Link to={`/admin/debates/${job.debate_id}`} className="truncate text-[11px] text-muted hover:text-text hover:underline">
        debate {job.debate_id.slice(0, 8)}
      </Link>
    )}
  </span>
);

const WORKER_COLUMNS: Column<WorkerInfo>[] = [
  {
    key: 'name',
    header: 'Worker',
    cell: (w) => (
      <span className="flex flex-col">
        <span className="font-mono text-[12px] text-text-2" title={w.name}>
          {w.hostname ?? w.name.slice(0, 12)}
        </span>
        <span className="text-[11px] text-muted">{w.queues.join(', ')}</span>
      </span>
    ),
  },
  {
    key: 'state',
    header: 'State',
    className: 'whitespace-nowrap',
    cell: (w) => <State tone={w.state === 'busy' ? 'warn' : w.state === 'idle' ? 'ok' : 'off'}>{w.state}</State>,
  },
  { key: 'job', header: 'Running', cell: (w) => (w.current_job ? <JobRef job={w.current_job} /> : <span className="text-dim">—</span>) },
  {
    key: 'beat',
    header: 'Heartbeat',
    className: 'whitespace-nowrap text-text-3',
    cell: (w) => {
      const age = secondsSince(w.last_heartbeat);
      return <span className={age !== null && age > 600 ? 'text-con' : ''}>{age === null ? '—' : `${formatSpan(age)} ago`}</span>;
    },
  },
  { key: 'up', header: 'Up', className: 'whitespace-nowrap text-text-3', cell: (w) => formatSpan(secondsSince(w.birth)) },
  { key: 'jobs', header: 'Done · failed', align: 'right', className: 'whitespace-nowrap', cell: (w) => `${w.successful} · ${w.failed}` },
];

/** RQ queues, workers, the cron scheduler and failed jobs (requeue / delete). */
export const QueuesSection = () => {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad(loadQueues, 15_000);
  const [target, setTarget] = useState<{ job: JobSummary; action: 'requeue' | 'delete' } | null>(null);

  const failedColumns: Column<JobSummary>[] = [
    { key: 'job', header: 'Job', cell: (j) => <JobRef job={j} /> },
    { key: 'queue', header: 'Queue', className: 'text-text-3', cell: (j) => j.queue },
    { key: 'when', header: 'Failed', className: 'whitespace-nowrap text-text-3', cell: (j) => (j.ended_at ? formatTime(j.ended_at) : '—') },
    {
      key: 'error',
      header: 'Error',
      cell: (j) =>
        j.error ? (
          <details className="max-w-[460px]">
            <summary className="cursor-pointer truncate text-xs text-con">{j.error.split('\n').filter(Boolean).pop()}</summary>
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-[10px] bg-ink p-2 font-mono text-[10px] text-text-3">{j.error}</pre>
          </details>
        ) : (
          <span className="text-dim">—</span>
        ),
    },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      className: 'whitespace-nowrap',
      cell: (j) => (
        <span className="inline-flex gap-1">
          <Button variant="ghost" size="sm" onClick={() => setTarget({ job: j, action: 'requeue' })}>
            Requeue
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setTarget({ job: j, action: 'delete' })}>
            Delete
          </Button>
        </span>
      ),
    },
  ];

  const scheduler = data?.schedulers[0];
  const schedulerAge = secondsSince(scheduler?.last_heartbeat);

  return (
    <SystemSection id="queues" title="Queues and workers" aside="every 15 s" loading={loading} error={error} onRefresh={() => reload()}>
      {data && (
        <div className="grid gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {data.queues.map((q) => (
              <Figure
                key={q.name}
                label={`${q.name} queue`}
                value={`${q.waiting} waiting`}
                tone={q.failed ? 'warn' : undefined}
                hint={`${q.started} running · ${q.failed} failed · ${q.scheduled + q.deferred} later`}
              />
            ))}
          </div>
          <Panel title="Workers" aside={`${data.workers.length} registered`}>
            <DataTable caption="Workers" columns={WORKER_COLUMNS} rows={data.workers} rowKey={(w) => w.name} empty="No worker is registered: nothing will run." />
          </Panel>
          <Panel
            title="Scheduler"
            aside={
              scheduler ? (
                <State tone={schedulerAge !== null && schedulerAge < 180 ? 'ok' : 'bad'}>
                  {scheduler.hostname ?? scheduler.name} · heartbeat {formatSpan(schedulerAge)} ago
                </State>
              ) : (
                <State tone="bad">not running: no trending refresh, no recovery checks</State>
              )
            }
          >
            <ul className="divide-y divide-line/70">
              {data.cron_jobs.map((c) => (
                <li key={c.name} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-xs">
                  <span className="font-mono text-[12px] text-text-2">{c.name}</span>
                  <span className="text-muted">every {formatSpan(c.interval_seconds)}</span>
                  <span className="text-muted">last queued {c.last_enqueued_at ? `${formatSpan(secondsSince(c.last_enqueued_at))} ago` : 'never'}</span>
                  <span className="ml-auto flex gap-1.5">
                    {c.recent.map((j) => (
                      <span key={j.id} title={`${j.status ?? '?'} · ${j.ended_at ? formatTime(j.ended_at) : ''}`} className={STATUS_TONES[j.status ?? ''] ?? 'text-muted'}>
                        {j.status ?? '?'}
                      </span>
                    ))}
                  </span>
                </li>
              ))}
              {data.cron_jobs.length === 0 && <li className="px-4 py-3 text-sm text-muted">No periodic job has run in the last days.</li>}
            </ul>
          </Panel>
          <Panel title="Failed jobs" aside={`${data.failed_jobs.length} kept by RQ`}>
            <DataTable caption="Failed jobs" columns={failedColumns} rows={data.failed_jobs} rowKey={(j) => j.id} empty="No failed jobs." />
          </Panel>
        </div>
      )}
      <ActionDialog
        open={target !== null}
        title={target?.action === 'requeue' ? 'Queue the job again?' : 'Delete the failed job?'}
        body={
          target?.action === 'requeue'
            ? 'It runs again as it was. A debate step that the watchdog already re-queued would run twice: check the debate first.'
            : 'It leaves the failed list; nothing runs.'
        }
        confirmLabel={target?.action === 'requeue' ? 'Requeue' : 'Delete'}
        danger={target?.action === 'delete'}
        autoFocusReason
        onClose={() => setTarget(null)}
        onSubmit={async (reason) => {
          if (!target) return;
          toast.success((await failedJobAction(target.job.id, target.action, reason)).message);
          reload();
        }}
      />
    </SystemSection>
  );
};
