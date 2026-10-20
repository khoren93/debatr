import { Suspense, lazy, useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router';
import { ArrowLeft, ArrowUpRight } from 'lucide-react';
import { getDebateCard } from '../../api/admin/debates';
import type { AdminDebateCard } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page } from '../../components/layout/AppShell';
import { DebateActions } from '../../components/admin/debates/DebateActions';
import { DebateFlags, DebateStatusText, ModerationText } from '../../components/admin/debates/DebateBits';
import { CoverPanel } from '../../components/admin/debates/CoverPanel';
import { ConfigPanel, MediaPanel, ModerationPanel, RecoveryPanel, UsagePanel } from '../../components/admin/debates/DebateSections';
import { Transcript } from '../../components/admin/debates/Transcript';
import { AuditPanel, LedgerTable, Panel } from '../../components/admin/users/UserSections';
import { formatTime, formatUsd } from '../../components/admin/helpers';
import { Card, ErrorBox, ModelIcon, Spinner } from '../../components/ui';
import { formatDuration, formatTokens, shortModelName } from '../../lib/format';

// The public page's player (Remotion): loaded only for a debate with audio.
const VideoPanel = lazy(() => import('../../components/admin/debates/VideoPanel'));

const Fact = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="min-w-0">
    <div className="text-[11px] text-muted">{label}</div>
    <div className="truncate text-[13px] text-text-2">{children}</div>
  </div>
);

const num = (value: unknown) => (typeof value === 'number' ? value : 0);

const AdminDebate = () => {
  const { id = '' } = useParams();
  const { me } = useAdminAuth();
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{ key: string; card: AdminDebateCard } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = `${id}:${version}`;
  const reload = useCallback(() => setVersion((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    getDebateCard(id)
      .then((card) => {
        if (!cancelled) {
          setResult({ key: `${id}:${version}`, card });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [id, version]);

  if (!me) return null;
  const card = result?.card.debate.id === id ? result.card : null;
  const d = card?.debate;

  return (
    <Page>
      <Link to="/admin/debates" className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-text">
        <ArrowLeft className="size-3.5" /> Debates
      </Link>
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!card && !error && <Spinner className="mt-10 size-6" />}

      {card && d && (
        <div className={`transition-opacity ${result?.key !== key ? 'opacity-60' : ''}`}>
          <Card className="mt-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-semibold">
                  <DebateStatusText status={d.status} />
                  <ModerationText status={d.moderation_status} />
                  <span className={d.is_public ? 'text-ok' : 'text-muted'}>{d.is_public ? 'public' : 'private'}</span>
                  <DebateFlags debate={d} />
                </div>
                <h1 className="mt-1.5 font-display text-2xl font-extrabold leading-tight tracking-tight">{card.topic || d.title}</h1>
              </div>
              <div className="flex shrink-0 items-center gap-3 text-xs">
                {d.url && (
                  <a href={d.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-muted hover:text-text">
                    Public page <ArrowUpRight className="size-3.5" />
                  </a>
                )}
              </div>
            </div>
            {d.error && <ErrorBox className="mt-3">{d.error}</ErrorBox>}

            <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-4 sm:grid-cols-3 lg:grid-cols-6">
              <Fact label="Owner">
                {d.owner ? (
                  <Link to={`/admin/users/${d.owner.id}`} className="hover:text-text hover:underline">
                    {d.owner.email}
                  </Link>
                ) : (
                  'none (legacy)'
                )}
              </Fact>
              <Fact label="Created">{formatTime(d.created_at)}</Fact>
              <Fact label="Ran">
                {d.duration_ms ? formatDuration(d.duration_ms) : '—'} · {d.turns} turns
              </Fact>
              <Fact label="Tokens">
                {formatTokens(num(card.totals.tokens_in))} in · {formatTokens(num(card.totals.tokens_out))} out
              </Fact>
              {d.cost !== null && (
                <Fact label="Cost · charged">
                  {formatUsd(d.cost)} · {formatUsd(d.charged ?? 0)}
                </Fact>
              )}
              <Fact label="Reach">
                {d.likes} likes · {d.votes} votes · {d.views} views
              </Fact>
              <Fact label="Topic">
                {card.motion ? (
                  <span title={card.motion.title ?? undefined}>
                    {card.motion.public_versions} public · {card.motion.debates} in all
                    {card.motion.url && (
                      <a href={card.motion.url} target="_blank" rel="noreferrer" className="ml-1.5 inline-flex items-center gap-0.5 text-muted hover:text-text">
                        page <ArrowUpRight className="size-3" />
                      </a>
                    )}
                  </span>
                ) : (
                  '—'
                )}
              </Fact>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {d.models.map((m, i) => (
                <Link
                  key={`${m}-${i}`}
                  to={`/admin/debates?model=${encodeURIComponent(m)}`}
                  title={`Debates with ${m}`}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line-2 bg-surface-2 px-2.5 py-1 text-xs text-text-2 hover:border-line-3"
                >
                  <ModelIcon modelId={m} size={13} /> {shortModelName(m)}
                </Link>
              ))}
              {d.own_key && <span className="text-xs text-muted">on the owner's OpenRouter key</span>}
              {d.via_token && <span className="text-xs text-muted">started with an API token</span>}
            </div>
            <div className="mt-5 border-t border-line pt-4">
              <DebateActions card={card} permissions={me.permissions} onChanged={reload} />
            </div>
          </Card>

          <div className="mt-4 grid items-start gap-4 xl:grid-cols-[2fr_1fr]">
            <div className="grid min-w-0 gap-4">
              {card.media.status === 'ready' && (
                <Suspense fallback={<Spinner className="mx-auto my-10 size-6" />}>
                  <VideoPanel debateId={d.id} builtAt={typeof card.media.finished_at === 'string' ? card.media.finished_at : null} />
                </Suspense>
              )}
              <Panel title="Transcript" aside={`${card.turns.length} turns`}>
                <Transcript turns={card.turns} />
              </Panel>
            </div>
            <div className="grid gap-4">
              <ModerationPanel card={card} />
              <CoverPanel card={card} permissions={me.permissions} onChanged={reload} />
              <MediaPanel card={card} />
              <RecoveryPanel card={card} />
            </div>
          </div>

          <div className="mt-4 grid gap-4">
            {card.usage && <UsagePanel usage={card.usage} />}
            {card.ledger && (
              <Panel title="Ledger" aside={card.refundable ? `${formatUsd(card.refundable)} refundable` : undefined}>
                <LedgerTable rows={card.ledger} />
              </Panel>
            )}
            <ConfigPanel card={card} />
            <AuditPanel targetId={d.id} targetType="debate" entries={card.audit} aside="last 50 about this debate" />
          </div>
        </div>
      )}
    </Page>
  );
};

export default AdminDebate;
