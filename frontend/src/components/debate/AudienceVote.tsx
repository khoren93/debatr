import { useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Check, Gavel } from 'lucide-react';
import { getErrorMessage } from '../../api/client';
import { castVote, retractVote } from '../../api/debates';
import type { Audience, DebateDetail } from '../../api/types';
import { shortModelName } from '../../lib/format';
import { Spinner, useToast } from '../ui';
import type { SpeakerInfo } from './helpers';
import { SpeakerTile } from './SpeakerTile';

interface Props {
  debate: DebateDetail;
  /** Debaters of the lineup (no host, no judge). */
  debaters: SpeakerInfo[];
  /** Results (and the judge's pick) are visible: the viewer voted, owns it or chose to peek. */
  revealed: boolean;
  onReveal: () => void;
  onChange: (audience: Audience) => void;
}

const percent = (n: number, total: number) => (total > 0 ? Math.round((n / total) * 100) : 0);

const linkButton = 'font-medium text-accent hover:text-accent-hover cursor-pointer';

/** "Who argued better?" — a blind audience vote, then the split next to the judge's pick. */
export const AudienceVote = ({ debate, debaters, revealed, onReveal, onChange }: Props) => {
  const toast = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const [pending, setPending] = useState<string | null>(null);
  const audience = debate.engagement.audience;
  const judgePick = debate.verdict && !debate.verdict.is_draw ? debate.verdict.winner_id : null;
  const showResults = revealed || audience.my_vote !== null;
  const canVote = audience.can_vote;
  const signIn = audience.reason === 'sign_in';
  const signInHref = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;

  const vote = async (id: string) => {
    if (signIn) {
      navigate(signInHref);
      return;
    }
    if (!canVote || pending) return;
    setPending(id);
    try {
      onChange(await (audience.my_vote === id ? retractVote(debate.id) : castVote(debate.id, id)));
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setPending(null);
    }
  };

  const retract = async () => {
    if (pending) return;
    setPending(audience.my_vote);
    try {
      onChange(await retractVote(debate.id));
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setPending(null);
    }
  };

  const mine = debaters.find((d) => d.id === audience.my_vote);
  let note: ReactNode;
  if (audience.reason === 'owner') note = 'You cannot vote on your own debate — this is how the audience sees it.';
  else if (mine) {
    note = (
      <>
        <span>You voted for {mine.name}.</span>
        <button type="button" onClick={retract} className={linkButton}>
          Change vote
        </button>
      </>
    );
  } else if (signIn) {
    note = (
      <>
        <span>Sign in to vote.</span>
        {!showResults && (
          <button type="button" onClick={onReveal} className={linkButton}>
            Show results and the verdict
          </button>
        )}
      </>
    );
  } else if (!showResults) {
    note = (
      <>
        <span>Results and the judge’s verdict appear after you vote.</span>
        <button type="button" onClick={onReveal} className={linkButton}>
          Just show me
        </button>
      </>
    );
  } else note = 'Cast your vote to add it to the split.';

  return (
    <section className="rounded-panel border border-white/6 bg-surface p-[clamp(18px,2.4vw,24px)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[11px] tracking-[0.08em] text-muted">AUDIENCE VOTE</div>
          <h2 className="mt-2 font-display text-[clamp(20px,2vw,24px)] font-bold tracking-[-0.02em]">Who argued better?</h2>
          <p className="mt-1 text-[13px] text-muted">Not who’s right — who made the stronger case.</p>
        </div>
        {showResults && (
          <div className="whitespace-nowrap font-mono text-xs text-muted">
            {audience.total} {audience.total === 1 ? 'vote' : 'votes'}
          </div>
        )}
      </div>

      <div className="mt-4 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]">
        {debaters.map((d) => {
          const share = percent(audience.counts[d.id] ?? 0, audience.total);
          const chosen = audience.my_vote === d.id;
          const clickable = canVote || signIn;
          return (
            <button
              key={d.id}
              type="button"
              onClick={() => vote(d.id)}
              disabled={!clickable || pending !== null}
              aria-pressed={chosen}
              className={`relative flex items-center gap-3 overflow-hidden rounded-[14px] border bg-ink px-4 py-3.5 text-left transition-colors ${clickable ? 'cursor-pointer hover:border-white/22' : 'cursor-default'} disabled:cursor-default`}
              style={{ borderColor: chosen ? d.color : 'rgba(255,255,255,0.08)' }}
            >
              <span className="absolute inset-y-0 left-0 transition-[width] duration-600 ease-[cubic-bezier(.2,.8,.2,1)]" style={{ width: showResults ? `${share}%` : '0%', background: `${d.color}29` }} aria-hidden="true" />
              <SpeakerTile model={d.model} color={d.color} size={40} className="relative !bg-surface" />
              <span className="relative min-w-0 flex-1">
                <span className="block truncate text-[15px] font-bold">{d.name}</span>
                <span className="mt-0.5 block truncate font-mono text-[11px] text-muted">
                  {d.tag} · {shortModelName(d.model)}
                </span>
                {showResults && judgePick === d.id && (
                  <span className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-accent/12 px-1.5 py-0.5 font-mono text-[10px] text-accent">
                    <Gavel className="size-3" /> JUDGE’S PICK
                  </span>
                )}
              </span>
              {pending === d.id ? (
                <Spinner className="relative size-4" />
              ) : showResults ? (
                <span className="relative flex items-center gap-1.5 font-display text-[22px] font-extrabold" style={{ color: d.color }}>
                  {chosen && <Check className="size-4" aria-label="Your vote" />}
                  {share}%
                </span>
              ) : (
                <span className="relative rounded-full border border-white/14 px-3 py-[7px] text-xs font-semibold text-text-2">Vote</span>
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-xs text-muted">{note}</div>
    </section>
  );
};
