import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Check, Gavel } from 'lucide-react';
import { getErrorMessage } from '../../api/client';
import { castVote, retractVote } from '../../api/debates';
import type { Audience, DebateDetail } from '../../api/types';
import { shortModelName, speakerColor } from '../../lib/format';
import { Card, LinkButton, SectionLabel, SpeakerBadge, Spinner, useToast } from '../ui';

interface Props {
  debate: DebateDetail;
  /** Results (and the judge's pick) are visible: the viewer voted, owns it or chose to peek. */
  revealed: boolean;
  onReveal: () => void;
  onChange: (audience: Audience) => void;
  className?: string;
}

const percent = (n: number, total: number) => (total > 0 ? Math.round((n / total) * 100) : 0);

/** "Who argued better?" — a blind audience vote, then the split next to the judge's pick. */
export const AudienceVote = ({ debate, revealed, onReveal, onChange, className = '' }: Props) => {
  const toast = useToast();
  const location = useLocation();
  const [pending, setPending] = useState<string | null>(null);
  const audience = debate.engagement.audience;
  const { participants } = debate;
  const debaters = participants.map((p, i) => ({ p, id: p.id ?? `participant_${i}` })).filter(({ p }) => p.role !== 'moderator');
  const judgePick = debate.verdict && !debate.verdict.is_draw ? debate.verdict.winner_id : null;
  const showResults = revealed || audience.my_vote !== null;
  const canVote = audience.can_vote;

  const vote = async (id: string) => {
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

  const signInHref = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
  let footer: React.ReactNode;
  if (audience.reason === 'owner') footer = 'You cannot vote on your own debate — this is how the audience sees it.';
  else if (audience.reason === 'sign_in') {
    footer = (
      <>
        <LinkButton to={signInHref} size="sm">
          Sign in to vote
        </LinkButton>
        {!showResults && (
          <button type="button" onClick={onReveal} className="text-muted underline-offset-2 hover:text-text hover:underline cursor-pointer">
            Show results and the verdict
          </button>
        )}
      </>
    );
  } else if (audience.my_vote) footer = 'Tap another debater to move your vote, or your pick again to take it back.';
  else if (!showResults) {
    footer = (
      <>
        <span>Judge’s verdict and the audience split open after your vote.</span>
        <button type="button" onClick={onReveal} className="text-muted underline-offset-2 hover:text-text hover:underline cursor-pointer">
          Just show me
        </button>
      </>
    );
  } else footer = 'Cast your vote to add it to the split.';

  return (
    <Card padding="sm" className={`!p-5 ${className}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionLabel>Audience vote</SectionLabel>
        {showResults && (
          <span className="font-mono text-[11px] text-muted">
            {audience.total} {audience.total === 1 ? 'vote' : 'votes'}
          </span>
        )}
      </div>
      <div className="mt-2 font-display text-xl font-bold tracking-[-0.02em]">Who argued better?</div>
      <p className="mt-1 text-[13px] text-muted">Not who is right — who made the stronger case.</p>

      <div className="mt-4 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]">
        {debaters.map(({ p, id }) => {
          const color = speakerColor(id, participants);
          const count = audience.counts[id] ?? 0;
          const share = percent(count, audience.total);
          const mine = audience.my_vote === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => vote(id)}
              disabled={!canVote || pending !== null}
              aria-pressed={mine}
              className={`relative overflow-hidden rounded-[14px] border bg-ink p-3.5 text-left transition-colors ${canVote ? 'cursor-pointer hover:border-line-3' : 'cursor-default'} disabled:cursor-default`}
              style={mine ? { borderColor: color } : undefined}
            >
              {showResults && <span className="absolute inset-y-0 left-0 transition-[width] duration-500" style={{ width: `${share}%`, background: `${color}22` }} aria-hidden="true" />}
              <span className="relative flex items-center gap-3">
                <SpeakerBadge name={p.name} color={color} size={34} imageUrl={p.avatar} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-sm font-bold">
                    <span className="truncate">{p.name ?? 'Debater'}</span>
                    {mine && <Check className="size-3.5 shrink-0" style={{ color }} aria-label="Your vote" />}
                  </span>
                  <span className="mt-0.5 block truncate text-[11px] text-muted">{shortModelName(p.model)}</span>
                </span>
                {pending === id ? (
                  <Spinner className="size-4" />
                ) : (
                  showResults && (
                    <span className="font-mono text-sm font-semibold" style={{ color }}>
                      {share}%
                    </span>
                  )
                )}
              </span>
              {showResults && judgePick === id && (
                <span className="relative mt-2.5 inline-flex items-center gap-1 rounded-md bg-host/15 px-1.5 py-0.5 font-mono text-[10px] text-host">
                  <Gavel className="size-3" /> JUDGE’S PICK
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted">{footer}</div>
    </Card>
  );
};
