import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import { deleteOrphans, getHealth, getProviders } from '../../../api/admin/system';
import type { MediaDir } from '../../../api/admin/types';
import { Button, Progress, useToast } from '../../ui';
import { ActionDialog } from '../ActionDialog';
import { DataTable, type Column } from '../DataTable';
import { formatBytes, formatSpan, formatTime, formatUsd, secondsSince } from '../helpers';
import { useLoad } from '../useLoad';
import { Panel } from '../users/UserSections';
import { Figure, Rows, State, SystemSection } from './SystemBits';

const loadProviders = (refresh: boolean) => getProviders(refresh);
const loadHealth = (refresh: boolean) => getHealth(refresh);
const BACKUP_MAX_HOURS = 26;

/** OpenRouter and ElevenLabs on the system keys, and how payments are set up. */
export const ProvidersSection = () => {
  const { data, loading, error, reload } = useLoad(loadProviders);
  const or = data?.openrouter;
  const el = data?.elevenlabs;
  const elShare = el?.limit ? (el.used ?? 0) / el.limit : 0;
  return (
    <SystemSection
      id="providers"
      title="Providers"
      aside={data ? `checked ${formatTime(data.checked_at)}, cached 5 min` : undefined}
      loading={loading}
      error={error}
      onRefresh={() => reload(true)}
    >
      {data && or && el && (
        <div className="grid items-start gap-4 lg:grid-cols-3">
          <Panel title="OpenRouter (system key)">
            <Rows
              rows={[
                ['Balance', or.balance !== undefined ? <span className={or.balance < 5 ? 'font-semibold text-con' : ''}>{formatUsd(or.balance)}</span> : '—'],
                ['Bought · used', or.total_credits !== undefined ? `${formatUsd(or.total_credits)} · ${formatUsd(or.total_usage ?? 0)}` : '—'],
                ['Key limit', or.key?.limit != null ? `${formatUsd(or.key.limit)} (${formatUsd(or.key.limit_remaining ?? 0)} left)` : 'none'],
                ['Used today', or.key?.usage_daily != null ? formatUsd(or.key.usage_daily) : '—'],
                ['Free tier', or.key?.is_free_tier == null ? '—' : or.key.is_free_tier ? 'yes (50 :free requests a day)' : 'no'],
                ...(or.error ? ([['Error', <span key="e" className="text-con">{or.error}</span>]] as [string, ReactNode][]) : []),
              ]}
            />
          </Panel>
          <Panel title="ElevenLabs (system key)">
            {el.configured ? (
              <>
                <Rows
                  rows={[
                    ['Key', el.ok ? <State tone="ok">accepted</State> : <State tone="bad">{el.reason ?? 'rejected'}</State>],
                    ['Plan', el.tier || '—'],
                    ['Characters', el.limit ? `${(el.used ?? 0).toLocaleString()} of ${el.limit.toLocaleString()}` : '—'],
                    ['Resets', el.resets_at ? formatTime(new Date(el.resets_at * 1000).toISOString()) : '—'],
                  ]}
                />
                {el.limit ? (
                  <div className="px-4 pb-3">
                    <Progress value={elShare} color={elShare > 0.9 ? '#FF7A66' : '#6C9CFF'} />
                  </div>
                ) : null}
              </>
            ) : (
              <p className="px-4 py-3 text-sm text-muted">No system key: only the free Edge voices and users' own keys.</p>
            )}
          </Panel>
          <Panel title="Payments">
            <Rows
              rows={[
                ['Mode', data.payments.mode],
                ['Top-ups', `${data.payments.topup_amounts.map((a) => `$${a}`).join(', ')} ${data.payments.currency.toUpperCase()}`],
                ['Signup bonus', formatUsd(data.payments.signup_bonus_usd)],
                ['Markup', `× ${data.payments.credit_markup}`],
                ['Premium voices', `${formatUsd(data.payments.tts_price_per_1k_chars)} per 1K characters`],
              ]}
            />
          </Panel>
        </div>
      )}
    </SystemSection>
  );
};

/** Database, Redis, disk and media folders, version, migrations, backups and settings. */
export const HealthSection = () => {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad(loadHealth);
  const [cleaning, setCleaning] = useState(false);
  if (!data) {
    return (
      <SystemSection id="health" title="Health" loading={loading} error={error} onRefresh={() => reload(true)}>
        {null}
      </SystemSection>
    );
  }
  const { database: db, redis, media } = data;
  const behind = data.alembic_current !== data.alembic_head;
  const backupAge = secondsSince(data.backup?.at);
  const backupOld = backupAge === null || backupAge > BACKUP_MAX_HOURS * 3600;
  const diskShare = media.disk_total ? (media.disk_used ?? 0) / media.disk_total : 0;
  const dirColumns: Column<MediaDir>[] = [
    {
      key: 'name',
      header: 'Folder',
      cell: (d) =>
        d.title ? (
          <Link to={`/admin/debates/${d.name}`} className="flex min-w-0 max-w-[360px] 2xl:max-w-[540px] flex-col hover:underline">
            <span className="truncate text-text-2">{d.title}</span>
            <span className="font-mono text-[11px] text-muted">{d.name}</span>
          </Link>
        ) : (
          <span className="font-mono text-[11px] text-muted">{d.name}</span>
        ),
    },
    { key: 'files', header: 'Files', align: 'right', className: 'text-text-3', cell: (d) => d.files },
    { key: 'size', header: 'Size', align: 'right', cell: (d) => formatBytes(d.bytes) },
  ];

  return (
    <SystemSection id="health" title="Health" aside={`media scanned ${formatTime(media.scanned_at)}`} loading={loading} error={error} onRefresh={() => reload(true)}>
      <div className="grid gap-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Figure label="Version" value={<span className="font-mono text-base">{data.version}</span>} hint={data.environment} />
          <Figure
            label="Database schema"
            value={<span className="font-mono text-base">{data.alembic_current ?? '?'}</span>}
            tone={behind ? 'warn' : undefined}
            hint={behind ? `code expects ${data.alembic_head ?? '?'}` : 'up to date'}
          />
          <Figure
            label="Last backup"
            value={backupAge === null ? 'never' : `${formatSpan(backupAge)} ago`}
            tone={backupOld ? (data.environment === 'production' ? 'bad' : 'warn') : 'ok'}
            hint={data.backup ? `${formatBytes(data.backup.bytes)} · copy off the server: ${data.backup.remote ?? 'off'}` : 'scripts/backup-db.sh records it'}
          />
          <Figure
            label="Disk"
            value={`${formatBytes(media.disk_free)} free`}
            tone={diskShare > 0.9 ? 'bad' : diskShare > 0.85 ? 'warn' : undefined}
            hint={`${formatBytes(media.disk_used)} of ${formatBytes(media.disk_total)} used`}
          />
        </div>

        <div className="grid items-start gap-4 lg:grid-cols-2">
          <Panel title="Postgres" aside={db.ok ? <State tone="ok">{db.latency_ms} ms</State> : <State tone="bad">down</State>}>
            {db.error && <p className="px-4 py-3 text-xs text-con">{db.error}</p>}
            <Rows rows={[['Size', formatBytes(db.bytes)], ['Connections', db.connections ?? '—']]} />
            <DataTable
              caption="Largest tables"
              columns={[
                { key: 'name', header: 'Table', cell: (t) => <span className="font-mono text-[12px] text-text-2">{t.name}</span> },
                { key: 'rows', header: 'Rows', align: 'right', className: 'text-text-3', cell: (t) => t.rows.toLocaleString() },
                { key: 'size', header: 'Size', align: 'right', cell: (t) => formatBytes(t.bytes) },
              ]}
              rows={db.tables}
              rowKey={(t) => t.name}
            />
          </Panel>
          <Panel title="Redis" aside={redis.ok ? <State tone="ok">{redis.latency_ms} ms</State> : <State tone="bad">down</State>}>
            {redis.error && <p className="px-4 py-3 text-xs text-con">{redis.error}</p>}
            <Rows
              rows={[
                ['Version', redis.version ?? '—'],
                ['Up', formatSpan(redis.uptime_seconds)],
                ['Memory', `${formatBytes(redis.used_memory)} (peak ${formatBytes(redis.peak_memory)})${redis.max_memory ? ` of ${formatBytes(redis.max_memory)}` : ''}`],
                ['Keys', redis.keys?.toLocaleString() ?? '—'],
              ]}
            />
          </Panel>
        </div>

        <div className="grid items-start gap-4 lg:grid-cols-2">
          <Panel title="Heaviest media folders" aside={`${formatBytes(media.bytes)} in ${media.dirs} folders`}>
            <DataTable caption="Heaviest media folders" columns={dirColumns} rows={media.heaviest} rowKey={(d) => d.name} empty="MEDIA_ROOT is empty." />
          </Panel>
          <Panel
            title="Orphan folders"
            aside={
              media.orphans.length > 0 && (
                <Button variant="danger" size="sm" icon={<Trash2 className="size-3.5" />} onClick={() => setCleaning(true)}>
                  Delete {media.orphans.length} ({formatBytes(media.orphan_bytes)})
                </Button>
              )
            }
          >
            <p className="border-b border-line px-4 py-2.5 text-xs text-muted">Folders of debates that no longer exist, untouched for an hour.</p>
            <DataTable caption="Orphan folders" columns={dirColumns} rows={media.orphans} rowKey={(d) => d.name} empty="No orphans." />
          </Panel>
        </div>

        <Panel title="Settings" aside="secrets only as set / not set">
          <div className="grid gap-x-8 px-4 py-2 sm:grid-cols-2 lg:grid-cols-3">
            {data.config.map((flag) => (
              <div key={flag.name} className="flex items-baseline justify-between gap-3 border-b border-line/50 py-1.5 text-xs">
                <span className="font-mono text-[11px] text-muted">{flag.name}</span>
                <span className={`truncate text-right ${flag.value === 'not set' ? 'text-dim' : 'text-text-2'}`} title={flag.value}>
                  {flag.value}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <ActionDialog
        open={cleaning}
        title={`Delete ${media.orphans.length} orphan folders?`}
        body={`${formatBytes(media.orphan_bytes)} of audio and pictures of debates that no longer exist. Each folder is checked again on the server first.`}
        confirmLabel="Delete folders"
        danger
        sudo
        autoFocusReason
        onClose={() => setCleaning(false)}
        onSubmit={async (reason) => {
          const out = await deleteOrphans(
            media.orphans.map((o) => o.name),
            reason,
          );
          toast.success(`Deleted ${out.deleted} folders (${formatBytes(out.bytes)})${out.skipped.length ? `; ${out.skipped.length} kept` : ''}`);
          reload(true);
        }}
      />
    </SystemSection>
  );
};
