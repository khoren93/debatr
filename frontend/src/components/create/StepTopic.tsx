import { ArrowRight, ArrowUpRight, X } from 'lucide-react';
import type { TrendingTopic } from '../../api/types';
import { formatAge } from '../../lib/format';
import { Dropdown, Hint } from '../ui';
import { Favicon, TrendingBrowser } from './TrendingBrowser';
import { LANGUAGES, LENGTH_OPTIONS, MAX_ROUNDS, MIN_ROUNDS, MIN_TOPIC_LENGTH, TOPIC_MAX_LENGTH, lengthOption, roundsHint, topicValid, type NewsPick, type WizardState } from './wizardState';

interface StepTopicProps {
  state: WizardState;
  patch: (patch: Partial<WizardState>) => void;
  showErrors: boolean;
  /** "~4 min episode · ~$0.02 estimated", null while unknown. */
  estimateLine: string | null;
  onContinue: () => void;
}

const ROUND_OPTIONS = Array.from({ length: MAX_ROUNDS - MIN_ROUNDS + 1 }, (_, i) => MIN_ROUNDS + i);

/** The linked trending story under the question: source, brief and a way to drop it. */
const LinkedStory = ({ news, onRemove }: { news: NewsPick; onRemove: () => void }) => (
  <div className="grid gap-2 rounded-[14px] border border-line bg-ink px-4 py-3">
    <div className="flex min-w-0 items-center gap-2 text-xs text-text-3">
      <Favicon url={news.url} />
      <span className="truncate font-semibold">{news.outlet || 'News story'}</span>
      {news.published_at && <span className="shrink-0 text-dim">· {formatAge(news.published_at)} ago</span>}
      {news.url && (
        <a href={news.url} target="_blank" rel="noreferrer noopener" title={news.title} className="ml-auto inline-flex shrink-0 items-center gap-1 font-semibold hover:text-accent">
          Read <ArrowUpRight className="size-[13px]" />
        </a>
      )}
      <button
        type="button"
        onClick={onRemove}
        title="Remove this topic"
        aria-label="Remove this topic"
        className={`grid size-6 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-text cursor-pointer ${news.url ? '' : 'ml-auto'}`}
      >
        <X className="size-3.5" />
      </button>
    </div>
    <p className="line-clamp-4 text-[13px] leading-normal text-muted">{news.brief}</p>
    <div className="text-[11px] leading-snug text-dim">The models read this brief before they argue. Editing the question unlinks the story.</div>
  </div>
);

/** Step 1: trending topics on the left, the debate's topic and format in a sticky panel. */
export const StepTopic = ({ state, patch, showErrors, estimateLine, onContinue }: StepTopicProps) => {
  const valid = topicValid(state);
  const knownLanguage = LANGUAGES.some((l) => l.value === state.language);
  const news = state.news;

  const pick = (topic: TrendingTopic, all: TrendingTopic[]) => {
    const source = topic.sources[0];
    const angle = state.description.trim();
    // The angle was written for the previously linked topic, or is a brief the old wizard copied
    // into it: it does not fit the new topic.
    const stale = Boolean(news) || (angle !== '' && all.some((t) => t.brief.trim() === angle));
    patch({
      topic: topic.question,
      news: { topic_id: topic.id, brief: topic.brief, outlet: source?.outlet ?? '', title: source?.title ?? '', url: source?.url ?? '', published_at: source?.published_at ?? null },
      ...(stale ? { description: '' } : {}),
    });
  };
  // Unselecting gives the question back: it belonged to the topic, not to the user.
  const unpick = () => patch({ topic: '', news: null });
  // Drafts carry the story without the trending topic id: their card is matched by the link.
  const isPicked = (topic: TrendingTopic) => Boolean(news) && (news?.topic_id ? topic.id === news.topic_id : Boolean(news?.url) && topic.sources[0]?.url === news?.url);

  return (
    <>
      <div className="mt-7 grid items-start gap-[22px] animate-rise min-[1180px]:grid-cols-2">
        <TrendingBrowser isPicked={isPicked} onPick={pick} onUnpick={unpick} onUseQuery={(q) => patch({ topic: q.replace(/\??$/, '?'), news: null })} />

        <aside className="grid min-w-0 gap-[18px] rounded-panel border border-line bg-surface p-5 min-[1180px]:sticky min-[1180px]:top-5">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-[19px] font-bold tracking-[-0.02em]">Your debate</h2>
            <span className="font-mono text-[10px] tracking-[0.08em] text-dim">STEP 1 OF 3</span>
          </div>

          <div className="grid gap-2">
            <div className="flex items-baseline justify-between gap-3">
              <label htmlFor="wizard-topic" className="text-[13px] font-semibold text-text-3">
                Topic
              </label>
              <span className="text-xs text-dim">{news ? 'From today’s news' : 'Pick one or write your own'}</span>
            </div>
            <textarea
              id="wizard-topic"
              rows={3}
              value={state.topic}
              // A trending topic stays linked only while its question is unchanged.
              onChange={(e) => patch(news ? { topic: e.target.value, news: null } : { topic: e.target.value })}
              placeholder="Are cryptocurrencies the future of finance or a bubble?"
              maxLength={TOPIC_MAX_LENGTH}
              className={`w-full resize-none rounded-[14px] border bg-ink px-4 py-3.5 font-display text-[19px] font-semibold leading-[1.3] tracking-[-0.01em] text-text outline-none transition-colors focus:border-accent ${
                valid ? 'border-accent/45' : 'border-line-2'
              }`}
            />
            {showErrors && !valid && <Hint tone="danger">Give the speakers a topic of at least {MIN_TOPIC_LENGTH} characters.</Hint>}
            {/* The question is drawn on the video: past three quarters of the limit, count down. */}
            {state.topic.length >= TOPIC_MAX_LENGTH * 0.75 && (
              <div className={`text-right font-mono text-[11px] ${state.topic.length >= TOPIC_MAX_LENGTH ? 'text-host' : 'text-dim'}`} aria-live="polite">
                {state.topic.length} / {TOPIC_MAX_LENGTH}
              </div>
            )}
            {news && <LinkedStory news={news} onRemove={unpick} />}
          </div>

          <div className="grid gap-2">
            <label htmlFor="wizard-angle" className="text-[13px] font-semibold text-text-3">
              Angle <span className="font-normal text-dim">(optional)</span>
            </label>
            <textarea
              id="wizard-angle"
              rows={news ? 3 : 5}
              value={state.description}
              onChange={(e) => patch({ description: e.target.value })}
              placeholder="Give the models a direction — what to focus on, what to avoid, facts they must use…"
              maxLength={4000}
              className="w-full resize-none rounded-field border border-line-2 bg-ink px-3.5 py-3 text-sm leading-normal text-text outline-none transition-colors focus:border-accent"
            />
          </div>

          <div>
            <div className="grid grid-cols-3 gap-2.5">
              <div className="grid min-w-0 gap-2">
                <span className="text-[13px] font-semibold text-text-3">Language</span>
                <Dropdown
                  aria-label="Language"
                  className="max-sm:gap-1.5 max-sm:px-2.5 max-sm:text-[13px]"
                  value={state.language}
                  onChange={(language) => patch({ language })}
                  menuWidth={180}
                  options={[...(knownLanguage ? [] : [{ value: state.language, label: state.language }]), ...LANGUAGES.map((l) => ({ value: l.value, label: l.label, text: l.value }))]}
                />
              </div>
              <div className="grid min-w-0 gap-2">
                <span className="text-[13px] font-semibold text-text-3">Rounds</span>
                <Dropdown
                  aria-label="Rounds"
                  className="max-sm:gap-1.5 max-sm:px-2.5 max-sm:text-[13px]"
                  value={state.num_rounds}
                  onChange={(num_rounds) => patch({ num_rounds })}
                  menuWidth={230}
                  options={ROUND_OPTIONS.map((n) => ({ value: n, label: `${n} ${n === 1 ? 'round' : 'rounds'}`, hint: roundsHint(n) }))}
                />
              </div>
              <div className="grid min-w-0 gap-2">
                <span className="text-[13px] font-semibold text-text-3">Reply length</span>
                <Dropdown
                  aria-label="Reply length"
                  className="max-sm:gap-1.5 max-sm:px-2.5 max-sm:text-[13px]"
                  value={state.length_preset}
                  onChange={(length_preset) => patch({ length_preset })}
                  menuWidth={230}
                  options={LENGTH_OPTIONS.map((o) => ({ value: o.value, label: o.label, hint: o.hint }))}
                />
              </div>
            </div>
            <div className="mt-2.5 font-mono text-[11px] text-dim">
              {roundsHint(state.num_rounds)} · {lengthOption(state.length_preset).hint}
            </div>
          </div>

          <div className="grid gap-2">
            <button
              type="button"
              onClick={onContinue}
              aria-disabled={!valid}
              className={`flex h-[50px] w-full items-center justify-center gap-2 rounded-[14px] font-display text-base font-extrabold tracking-[-0.01em] transition-colors cursor-pointer ${
                valid ? 'bg-accent text-ink hover:bg-accent-hover' : 'cursor-not-allowed bg-surface-3 text-dim'
              }`}
            >
              Continue to speakers <ArrowRight className="size-4" strokeWidth={2.5} />
            </button>
            <div className="text-center font-mono text-[11px] text-dim">{estimateLine ?? ' '}</div>
          </div>
        </aside>
      </div>

      {/* Room for the bar below, so the end of the page can scroll out from under it. */}
      <div className="h-16 md:hidden" aria-hidden="true" />

      {/* Phones: the panel sits below the topic list, so keep the way forward in reach. Outside
          the animated step: a running transform animation would pin "fixed" to the step. The
          backdrop runs down behind the tab bar, so no card shows between the bar and the tabs. */}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-25 bg-linear-to-t from-ink from-80% to-transparent px-3 pt-5 pb-[calc(76px+env(safe-area-inset-bottom))] md:hidden">
        <div className="pointer-events-auto flex items-center gap-3 rounded-[16px] border border-line-2 bg-surface-2 py-2.5 pr-2.5 pl-4 shadow-[0_20px_40px_-16px_rgba(0,0,0,0.8)]">
          <div className="min-w-0 flex-1 truncate text-[13px] font-semibold">{valid ? state.topic.trim() : 'Pick a topic to continue'}</div>
          <button
            type="button"
            onClick={onContinue}
            aria-disabled={!valid}
            className={`flex h-10 shrink-0 items-center rounded-[11px] px-4 text-sm font-bold cursor-pointer ${valid ? 'bg-accent text-ink' : 'cursor-not-allowed bg-surface-3 text-dim'}`}
          >
            Continue →
          </button>
        </div>
      </div>
    </>
  );
};
