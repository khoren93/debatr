import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { ArrowUpRight, Ban, CheckCircle2, ShieldCheck } from 'lucide-react';
import { debateAction, getDebateCard, getModerationQueue } from '../../api/admin/debates';
import type { AdminDebateCard, ModerationQueue } from '../../api/admin/types';
import { getErrorMessage } from '../../api/client';
import { Page, PageTitle } from '../../components/layout/AppShell';
import { ActionDialog } from '../../components/admin/ActionDialog';
import { Transcript } from '../../components/admin/debates/Transcript';
import { Panel } from '../../components/admin/users/UserSections';
import { formatTime } from '../../components/admin/helpers';
import { Button, Card, ErrorBox, ModelIcon, Spinner, useToast } from '../../components/ui';
import { formatAgo } from '../../lib/format';

type Decision = 'approve' | 'reject';

const Kbd = ({ children }: { children: string }) => (
  <kbd className="rounded border border-line-2 bg-surface-2 px-1.5 py-px font-mono text-[10px] text-text-3">{children}</kbd>
);

/** Typing in a field never triggers the queue's keys. */
const typing = (target: EventTarget | null) => {
  const el = target as HTMLElement | null;
  return Boolean(el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable));
};

const AdminModeration = () => {
  const toast = useToast();
  const navigate = useNavigate();
  const [version, setVersion] = useState(0);
  const [queue, setQueue] = useState<ModerationQueue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [card, setCard] = useState<AdminDebateCard | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [cardError, setCardError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getModerationQueue()
      .then((data) => {
        if (!cancelled) {
          setQueue(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [version]);

  const items = queue?.flagged ?? [];
  // The selection survives reloads while its debate is still flagged; otherwise the first one.
  const current = items.find((i) => i.id === selected) ?? items[0] ?? null;
  const index = current ? items.indexOf(current) : -1;
  const currentId = current?.id ?? null;

  useEffect(() => {
    if (!currentId) return;
    let cancelled = false;
    getDebateCard(currentId)
      .then((data) => {
        if (!cancelled) {
          setCard(data);
          setCardError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setCardError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [currentId, version]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const list = queue?.flagged ?? [];
      const at = list.findIndex((i) => i.id === currentId);
      if (decision || typing(e.target) || e.metaKey || e.ctrlKey || e.altKey || at < 0) return;
      const move = (step: number) => {
        const next = list[Math.min(list.length - 1, Math.max(0, at + step))];
        if (next) setSelected(next.id);
      };
      if (e.key === 'j' || e.key === 'ArrowDown') move(1);
      else if (e.key === 'k' || e.key === 'ArrowUp') move(-1);
      else if (e.key === 'a') setDecision('approve');
      else if (e.key === 'r') setDecision('reject');
      else if (e.key === 'o') navigate(`/admin/debates/${list[at].id}`);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [queue, currentId, decision, navigate]);

  const decide = async (reason: string) => {
    if (!current || !decision) return;
    const out = await debateAction(current.id, decision, reason);
    toast.success(out.message);
    // Move on to the next flagged debate (or the one before when this was the last).
    const next = items[index + 1] ?? items[index - 1] ?? null;
    setSelected(next?.id ?? null);
    setVersion((n) => n + 1);
  };

  const shown = card && current && card.debate.id === current.id ? card : null;

  return (
    <Page>
      <PageTitle
        kicker="Admin console"
        title="Moderation"
        right={
          <div className="hidden items-center gap-1.5 text-xs text-muted md:flex">
            <Kbd>j</Kbd>
            <Kbd>k</Kbd> move · <Kbd>a</Kbd> approve · <Kbd>r</Kbd> reject · <Kbd>o</Kbd> open · <Kbd>⌘↵</Kbd> send
          </div>
        }
      />
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!queue && !error && <Spinner className="mt-10 size-6" />}

      {queue && items.length === 0 && (
        <Card padding="sm" className="mt-6 flex items-center gap-2 text-sm text-text-3">
          <ShieldCheck className="size-4 text-ok" /> Nothing waits for moderation.
        </Card>
      )}

      {queue && current && (
        <div className="mt-6 grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <Panel title="Flagged" aside={`${items.length} waiting, oldest first`}>
            <ul className="max-h-[70vh] divide-y divide-line/70 overflow-y-auto" role="listbox" aria-label="Flagged debates">
              {items.map((item) => (
                <li key={item.id} role="option" aria-selected={item.id === current.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(item.id)}
                    className={`grid w-full cursor-pointer gap-1 px-4 py-3 text-left transition-colors ${item.id === current.id ? 'bg-surface-2' : 'hover:bg-surface-2/60'}`}
                  >
                    <span className="line-clamp-2 text-sm font-semibold text-text-2">{item.title}</span>
                    <span className="line-clamp-2 text-xs text-host">{item.reason ?? 'no reason given'}</span>
                    <span className="flex flex-wrap items-center gap-x-2 text-[11px] text-muted">
                      {item.models.map((m, i) => (
                        <ModelIcon key={`${m}-${i}`} modelId={m} size={12} />
                      ))}
                      <span>{item.owner?.email ?? 'no owner'}</span>
                      <span>· {formatAgo(item.ended_at ?? item.created_at)}</span>
                      {item.source === 'fallback' && <span className="text-con">· check gave no answer</span>}
                      {item.publish_requested && <span>· owner wants it public</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel
            title="Transcript"
            aside={
              <Link to={`/admin/debates/${current.id}`} className="inline-flex items-center gap-1 hover:text-text">
                Open the debate <ArrowUpRight className="size-3.5" />
              </Link>
            }
          >
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-text">{current.title}</div>
                <div className="mt-0.5 text-xs text-host">
                  {current.reason ?? 'no reason given'} <span className="text-muted">· {current.source ?? 'unknown'} check</span>
                </div>
              </div>
              <div className="flex gap-2">
                <Button size="sm" icon={<CheckCircle2 className="size-4" />} onClick={() => setDecision('approve')}>
                  Approve
                </Button>
                <Button size="sm" variant="danger" icon={<Ban className="size-4" />} onClick={() => setDecision('reject')}>
                  Reject
                </Button>
              </div>
            </div>
            {current.cover_url && (
              // Its AI cover goes to the gallery with it: judged together with the text.
              <div className="border-b border-line px-4 py-3">
                <img src={current.cover_url} alt="AI cover" className="aspect-video w-full max-w-[420px] rounded-[10px] border border-line object-cover" />
              </div>
            )}
            {cardError ? <ErrorBox className="m-4">{cardError}</ErrorBox> : shown ? <Transcript turns={shown.turns} folded={false} /> : <Spinner className="m-4 size-5" />}
          </Panel>
        </div>
      )}

      {queue && (
        <div className="mt-6">
          <Panel title="Recent decisions" aside="last 30">
            {queue.recent.length === 0 ? (
              <p className="px-4 py-4 text-sm text-muted">No decisions yet.</p>
            ) : (
              <ul className="divide-y divide-line/70">
                {queue.recent.map((r, i) => (
                  <li key={`${r.debate_id}-${r.created_at}-${i}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-2.5 text-xs">
                    <span className={r.action === 'moderation.approved' ? 'font-semibold text-ok' : 'font-semibold text-con'}>
                      {r.action === 'moderation.approved' ? 'approved' : 'rejected'}
                    </span>
                    {r.debate_id && r.title ? (
                      <Link to={`/admin/debates/${r.debate_id}`} className="min-w-0 truncate text-text-2 hover:underline">
                        {r.title}
                      </Link>
                    ) : (
                      <span className="text-muted">a deleted debate</span>
                    )}
                    {r.reason && <span className="text-text-3">“{r.reason}”</span>}
                    <span className="ml-auto whitespace-nowrap text-muted">
                      {r.actor_email ?? 'unknown'} · {formatTime(r.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}

      <ActionDialog
        open={decision !== null}
        title={decision === 'approve' ? 'Approve for the gallery?' : 'Reject it?'}
        body={
          decision === 'approve'
            ? current?.publish_requested
              ? 'The owner wants it public: it goes to the gallery now.'
              : 'It stays private (the owner did not ask for the gallery).'
            : 'It stays out of the gallery and the owner cannot publish it.'
        }
        confirmLabel={decision === 'approve' ? 'Approve' : 'Reject'}
        danger={decision === 'reject'}
        autoFocusReason
        onClose={() => setDecision(null)}
        onSubmit={decide}
      />
    </Page>
  );
};

export default AdminModeration;
