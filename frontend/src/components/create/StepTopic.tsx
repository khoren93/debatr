import { ArrowRight } from 'lucide-react';
import type { TrendingTopic } from '../../api/types';
import { Dropdown, Hint, SwitchTrack } from '../ui';
import { TrendingBrowser } from './TrendingBrowser';
import { LANGUAGES, LENGTH_OPTIONS, MAX_ROUNDS, MIN_ROUNDS, MIN_TOPIC_LENGTH, lengthOption, roundsHint, topicValid, type WizardState } from './wizardState';

interface StepTopicProps {
  state: WizardState;
  patch: (patch: Partial<WizardState>) => void;
  showErrors: boolean;
  /** "~4 min episode · ~$0.02 estimated", null while unknown. */
  estimateLine: string | null;
  onContinue: () => void;
}

const ROUND_OPTIONS = Array.from({ length: MAX_ROUNDS - MIN_ROUNDS + 1 }, (_, i) => MIN_ROUNDS + i);

/** Step 1: trending topics on the left, the debate's topic and format in a sticky panel. */
export const StepTopic = ({ state, patch, showErrors, estimateLine, onContinue }: StepTopicProps) => {
  const valid = topicValid(state);
  const knownLanguage = LANGUAGES.some((l) => l.value === state.language);
  const news = state.news;

  const pick = (topic: TrendingTopic) => {
    const source = topic.sources[0];
    patch({
      topic: topic.question,
      news: { topic_id: topic.id, brief: topic.brief, outlet: source?.outlet ?? '', title: source?.title ?? '', url: source?.url ?? '', published_at: source?.published_at ?? null },
      ground: true,
    });
  };
  // Drafts carry the story without the trending topic id: their card is matched by the link.
  const isPicked = (topic: TrendingTopic) => Boolean(news) && (news?.topic_id ? topic.id === news.topic_id : Boolean(news?.url) && topic.sources[0]?.url === news?.url);

  const cta = (
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
  );

  return (
    <>
    <div className="mt-7 grid items-start gap-[22px] animate-rise min-[1180px]:grid-cols-2">
      <TrendingBrowser isPicked={isPicked} onPick={pick} onUseQuery={(q) => patch({ topic: q.replace(/\??$/, '?'), news: null })} />

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
            <span className="text-xs text-dim">Pick one or write your own</span>
          </div>
          <textarea
            id="wizard-topic"
            rows={3}
            value={state.topic}
            // Clearing the question drops the story of the trending topic it came from.
            onChange={(e) => patch(e.target.value.trim() ? { topic: e.target.value } : { topic: e.target.value, news: null })}
            placeholder="Are cryptocurrencies the future of finance or a bubble?"
            maxLength={500}
            className={`w-full resize-none rounded-[14px] border bg-ink px-4 py-3.5 font-display text-[19px] font-semibold leading-[1.3] tracking-[-0.01em] text-text outline-none transition-colors focus:border-accent ${
              valid ? 'border-accent/45' : 'border-line-2'
            }`}
          />
          {showErrors && !valid && <Hint tone="danger">Give the speakers a topic of at least {MIN_TOPIC_LENGTH} characters.</Hint>}
        </div>

        <div className="grid gap-2">
          <label htmlFor="wizard-angle" className="text-[13px] font-semibold text-text-3">
            Angle <span className="font-normal text-dim">(optional)</span>
          </label>
          <textarea
            id="wizard-angle"
            rows={5}
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

        {news && (
          <button
            type="button"
            role="switch"
            aria-checked={state.ground}
            onClick={() => patch({ ground: !state.ground })}
            className="flex items-center justify-between gap-3 rounded-[14px] border border-line bg-ink px-4 py-3.5 text-left cursor-pointer"
          >
            <span className="min-w-0">
              <span className="block text-[13px] font-semibold">Ground in the {(news.outlet || 'news').replace(/^the\s+/i, '')} article</span>
              <span className="mt-0.5 block text-xs text-muted">Models read a brief of the story before they argue.</span>
            </span>
            <SwitchTrack on={state.ground} />
          </button>
        )}

        <div className="grid gap-2">
          {cta}
          <div className="text-center font-mono text-[11px] text-dim">{estimateLine ?? ' '}</div>
        </div>
      </aside>
    </div>

      {/* Phones: the panel sits below the topic list, so keep the way forward in reach. Outside
          the animated step: a running transform animation would pin "fixed" to the step. */}
      <div className="fixed inset-x-3 bottom-[calc(76px+env(safe-area-inset-bottom))] z-25 flex items-center gap-3 rounded-[16px] border border-line-2 bg-surface-2/95 py-2.5 pr-2.5 pl-4 shadow-[0_20px_40px_-16px_rgba(0,0,0,0.8)] backdrop-blur-[14px] md:hidden">
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
    </>
  );
};
