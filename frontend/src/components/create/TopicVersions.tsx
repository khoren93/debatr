import { Link } from 'react-router';
import { Layers, Repeat2, X } from 'lucide-react';
import { useMotionSuggestions } from '../../hooks/useMotionSuggestions';
import { TOPIC_MAX_LENGTH, type WizardState } from './wizardState';

interface TopicVersionsProps {
  state: WizardState;
  patch: (patch: Partial<WizardState>) => void;
}

const versionsLabel = (n: number) => `${n} ${n === 1 ? 'version' : 'versions'}`;

/**
 * Under the topic: the remix link, the published topic this debate will be a version of (same
 * question after case and punctuation, or a remix's translation) or, when there is none, similar
 * published topics whose wording the user can take to join them.
 */
export const TopicVersions = ({ state, patch }: TopicVersionsProps) => {
  const { data, fresh } = useMotionSuggestions(state.topic, state.language, state.remix?.id);
  const match = fresh ? (data?.match ?? null) : null;
  const similar = data && !match ? data.similar : [];
  // Another wording is another question: a linked news story does not follow it.
  const takeWording = (title: string) => {
    const topic = title.slice(0, TOPIC_MAX_LENGTH);
    patch(state.news ? { topic, news: null } : { topic });
  };

  if (!state.remix && !match && similar.length === 0) return null;
  return (
    <div className="grid gap-2">
      {state.remix && (
        <div className="flex min-w-0 items-center gap-2 rounded-[12px] border border-line bg-ink py-1.5 pr-1.5 pl-3 text-xs text-text-3">
          <Repeat2 className="size-3.5 shrink-0 text-accent" />
          <span className="min-w-0 flex-1 truncate" title={state.remix.topic}>
            Remix of <span className="font-semibold text-text-2">{state.remix.topic}</span>
          </span>
          <button
            type="button"
            onClick={() => patch({ remix: null })}
            title="Not a remix: start it as a debate of its own"
            aria-label="Unlink the remix"
            className="grid size-6 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-text cursor-pointer"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}
      {match && (
        <div className="flex min-w-0 items-start gap-2 rounded-[12px] border border-accent/30 bg-accent/5 px-3 py-2 text-xs leading-snug text-text-3">
          <Layers className="mt-px size-3.5 shrink-0 text-accent" />
          <span className="min-w-0">
            Joins a published topic as another version ·{' '}
            <Link to={`/t/${match.slug}`} target="_blank" rel="noreferrer" className="font-semibold text-accent hover:text-accent-hover">
              {versionsLabel(match.versions)} so far
            </Link>
          </span>
        </div>
      )}
      {similar.length > 0 && (
        <div className="grid gap-1.5">
          <div className="text-[11px] leading-snug text-dim">Similar topics were debated before. Take one’s wording to add your debate as a version of it:</div>
          {similar.map((m) => (
            <div key={m.slug} className="flex min-w-0 items-center gap-2 rounded-[12px] border border-line bg-ink py-1.5 pr-1.5 pl-3">
              <Link to={`/t/${m.slug}`} target="_blank" rel="noreferrer" title={m.title} className="min-w-0 flex-1 truncate text-[13px] font-semibold text-text-2 hover:text-text">
                {m.title}
              </Link>
              <span className="shrink-0 font-mono text-[10px] text-dim">{versionsLabel(m.versions)}</span>
              <button type="button" onClick={() => takeWording(m.title)} className="h-7 shrink-0 rounded-md px-2.5 text-xs font-semibold text-accent hover:bg-accent/10 cursor-pointer">
                Use
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
