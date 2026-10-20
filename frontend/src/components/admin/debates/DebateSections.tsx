import type { ReactNode } from 'react';
import type { AdminDebateCard, UsageByPurpose } from '../../../api/admin/types';
import { formatCount, formatDuration } from '../../../lib/format';
import { SOURCE_COLORS, SOURCE_LABELS } from '../charts/palette';
import { DataTable, type Column } from '../DataTable';
import { formatTime, formatUsd } from '../helpers';
import { Panel } from '../users/UserSections';
import { ModerationText } from './DebateBits';

const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value : null);
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const record = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {});

const Row = ({ label, children }: { label: ReactNode; children: ReactNode }) => (
  <div className="flex items-baseline justify-between gap-4 py-1.5 text-xs">
    <span className="shrink-0 text-muted">{label}</span>
    <span className="min-w-0 text-right text-text-2 [overflow-wrap:anywhere]">{children}</span>
  </div>
);

const Dot = ({ on, good = true }: { on: boolean; good?: boolean }) => (
  <span className={`inline-block size-2 rounded-full ${on ? (good ? 'bg-ok' : 'bg-host') : 'bg-surface-4'}`} aria-hidden="true" />
);

const when = (value: unknown) => (text(value) ? formatTime(value as string) : '—');

/** The AI check and the admin's decision, and the judge's verdict. */
export const ModerationPanel = ({ card }: { card: AdminDebateCard }) => {
  const m = card.moderation;
  const verdict = card.verdict;
  return (
    <Panel title="Moderation and verdict">
      <div className="divide-y divide-line/70 px-4 py-2">
        <Row label="Status">
          <ModerationText status={card.debate.moderation_status} />
        </Row>
        <Row label="Gallery">{card.debate.is_public ? 'public' : card.wants_public ? 'private, the owner wants it public' : 'private by choice'}</Row>
        {text(m.reason) && <Row label="Check said">{text(m.reason)}</Row>}
        <Row label="Decided by">
          {text(m.source) ?? '—'}
          {text(m.checked_at) && <span className="text-muted"> · {when(m.checked_at)}</span>}
        </Row>
        {text(m.admin_reason) && <Row label="Admin's reason">{text(m.admin_reason)}</Row>}
        <Row label="Verdict">{text(verdict.headline) ?? <span className="text-muted">none</span>}</Row>
        {text(verdict.winner_name) && <Row label="Winner">{text(verdict.winner_name)}</Row>}
      </div>
    </Panel>
  );
};

/** Views by where they came from (its page and players on other sites) and the sites that embed
 *  it. Views counted before sources were kept show as one line. */
export const ViewsPanel = ({ card }: { card: AdminDebateCard }) => {
  const v = card.views;
  return (
    <Panel title="Views" aside={`${formatCount(v.total)} in all · ${formatCount(v.last_7d)} in 7 days`}>
      {v.total === 0 ? (
        <p className="px-4 py-4 text-sm text-muted">Nobody has watched it yet.</p>
      ) : (
        <div className="divide-y divide-line/70 px-4 py-2">
          {v.sources.map((row) => (
            <Row
              key={row.source}
              label={
                <span className="inline-flex items-center gap-2">
                  <span className="size-2 rounded-[2px]" style={{ background: SOURCE_COLORS[row.source] }} aria-hidden="true" />
                  {SOURCE_LABELS[row.source]}
                </span>
              }
            >
              {formatCount(row.page + row.embed)}
              {row.embed > 0 && <span className="text-muted"> · {row.page ? `${formatCount(row.embed)} in players elsewhere` : 'in players elsewhere'}</span>}
            </Row>
          ))}
          {v.untracked > 0 && <Row label="Before sources were kept">{formatCount(v.untracked)}</Row>}
          {v.embeds.length > 0 && (
            <Row label="Embedded on">
              {v.embeds.map((site, i) => (
                <span key={site.host}>
                  {i > 0 && ', '}
                  <a href={`https://${site.host}`} target="_blank" rel="noreferrer noopener" className="hover:text-text">
                    {site.host}
                  </a>
                  <span className="text-muted"> · {formatCount(site.views)}</span>
                </span>
              ))}
            </Row>
          )}
        </div>
      )}
    </Panel>
  );
};

/** The audio build: options, progress, numbers and error. */
export const MediaPanel = ({ card }: { card: AdminDebateCard }) => {
  const media = card.media;
  const options = record(media.options);
  const stats = record(media.stats);
  const renders = record(media.renders);
  const voices = Object.keys(record(options.voices)).length;
  return (
    <Panel title="Audio" aside={media.status}>
      {media.status === 'none' && !text(media.error) ? (
        <p className="px-4 py-4 text-sm text-muted">No audio was built.</p>
      ) : (
        <div className="divide-y divide-line/70 px-4 py-2">
          <Row label="Voices">
            {text(options.provider) ?? '—'}
            {voices > 0 && ` · ${voices} picked`}
            {media.own_tts_key === true && ' · own key'}
            {media.free === true && ' · free rebuild'}
            {media.auto === true && ' · automatic'}
          </Row>
          <Row label="Scenes">
            {options.visuals === false ? 'off' : 'on'}
            {text(options.images) && ` · pictures ${text(options.images)}`}
          </Row>
          {num(stats.total_ms) !== null && <Row label="Length">{formatDuration(num(stats.total_ms))}</Row>}
          {num(stats.chars) !== null && <Row label="Characters">{num(stats.chars)?.toLocaleString()}</Row>}
          {text(media.message) && media.status !== 'ready' && <Row label="Step">{text(media.message)}</Row>}
          <Row label="Built">
            {when(media.started_at)} → {when(media.finished_at)}
          </Row>
          {Object.keys(renders).length > 0 && (
            <Row label="MP4 exports">
              {Object.entries(renders)
                .map(([kind, n]) => `${kind} ${String(n)}`)
                .join(' · ')}
            </Row>
          )}
          {text(media.error) && <Row label="Error">{<span className="text-con">{text(media.error)}</span>}</Row>}
        </div>
      )}
    </Panel>
  );
};

/** What Redis says about the runs right now (heartbeats, recovery, keys waiting). */
export const RecoveryPanel = ({ card }: { card: AdminDebateCard }) => {
  const r = card.recovery;
  return (
    <Panel title="Workers">
      <div className="divide-y divide-line/70 px-4 py-2">
        <Row label="Debate step running">
          <Dot on={r.debate_beat} />
        </Row>
        <Row label="Audio build running">
          <Dot on={r.media_beat} />
        </Row>
        <Row label="Recovered by the watchdog">
          {r.debate_attempts} debate · {r.media_attempts} audio
        </Row>
        <Row label="Stop requested">
          <Dot on={r.stop_flag} good={false} />
        </Row>
        <Row label="Own keys waiting">
          {[r.provider_key && 'OpenRouter', r.tts_key && 'ElevenLabs'].filter(Boolean).join(', ') || 'none'}
        </Row>
      </div>
    </Panel>
  );
};

const USAGE_COLUMNS: Column<UsageByPurpose>[] = [
  { key: 'purpose', header: 'Purpose', cell: (u) => <span className="font-mono text-[12px] text-text-2">{u.purpose}</span> },
  { key: 'key', header: 'Key', className: 'text-text-3', cell: (u) => u.key_owner },
  { key: 'calls', header: 'Calls', align: 'right', cell: (u) => u.calls },
  { key: 'failures', header: 'Failed', align: 'right', cell: (u) => (u.failures ? <span className="text-con">{u.failures}</span> : 0) },
  { key: 'cost', header: 'Cost', align: 'right', cell: (u) => formatUsd(u.cost) },
];

/** Provider calls of the debate by purpose (retries and studio calls included). */
export const UsagePanel = ({ usage }: { usage: UsageByPurpose[] }) => (
  <Panel title="Provider calls" aside="retries and studio calls included">
    <DataTable caption="Provider calls" columns={USAGE_COLUMNS} rows={usage} rowKey={(u) => `${u.purpose}:${u.key_owner}`} empty="No calls recorded (before usage tracking, or nothing ran)." />
  </Panel>
);

/** The stored configuration and totals as JSON, folded. */
export const ConfigPanel = ({ card }: { card: AdminDebateCard }) => (
  <Panel title="Configuration">
    <details className="group">
      <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-muted hover:text-text">Show the stored config and totals</summary>
      <pre className="max-h-[480px] overflow-auto border-t border-line px-4 py-3 font-mono text-[11px] leading-relaxed text-text-3">
        {JSON.stringify({ config: card.config, totals: card.totals }, null, 2)}
      </pre>
    </details>
  </Panel>
);
