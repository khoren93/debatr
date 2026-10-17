import { useState } from 'react';
import { useTrendingTopics } from '../../hooks/useTrendingTopics';
import { Card, Chip, Hint, Label, Segmented, Select, Textarea } from '../ui';
import { LANGUAGES, LENGTH_OPTIONS, MAX_ROUNDS, MIN_ROUNDS, MIN_TOPIC_LENGTH, lengthOption, topicValid, type WizardState } from './wizardState';

interface StepTopicProps {
  state: WizardState;
  patch: (patch: Partial<WizardState>) => void;
  showErrors: boolean;
}

const TRENDING_PREVIEW = 8;
// Long questions wrap instead of widening the page on phones.
const WRAP = 'whitespace-normal! text-left';
const ROUND_OPTIONS = Array.from({ length: MAX_ROUNDS - MIN_ROUNDS + 1 }, (_, i) => ({ value: MIN_ROUNDS + i, label: String(MIN_ROUNDS + i) }));

export const StepTopic = ({ state, patch, showErrors }: StepTopicProps) => {
  const [showAll, setShowAll] = useState(false);
  const trending = useTrendingTopics().data?.topics ?? [];
  const trendingShown = showAll ? trending : trending.slice(0, TRENDING_PREVIEW);
  const knownLanguage = LANGUAGES.some((l) => l.value === state.language);

  return (
    <div className="mt-[30px] grid gap-5 animate-rise">
      <Card padding="lg">
        <Label>What should they argue about?</Label>
        <textarea
          rows={2}
          value={state.topic}
          onChange={(e) => patch({ topic: e.target.value })}
          placeholder="Are cryptocurrencies the future of finance or a bubble?"
          maxLength={500}
          autoFocus
          className="mt-2.5 w-full resize-none rounded-[14px] border border-line-2 bg-ink px-4.5 py-4 font-display text-[clamp(18px,2vw,24px)] font-semibold leading-[1.3] tracking-[-0.01em] text-text outline-none transition-colors focus:border-accent"
        />
        {showErrors && !topicValid(state) && <Hint tone="danger">Give the speakers a topic of at least {MIN_TOPIC_LENGTH} characters.</Hint>}

        {trending.length > 0 && (
          <>
            <div className="mt-4 text-xs text-muted">Trending today</div>
            <div className="mt-2.5 flex flex-wrap gap-2">
              {trendingShown.map((t) => (
                <Chip key={t.id} active={state.topic === t.question} title={t.brief} onClick={() => patch({ topic: t.question, description: t.brief })} className={WRAP}>
                  {t.question}
                </Chip>
              ))}
              {trending.length > TRENDING_PREVIEW && (
                <button type="button" onClick={() => setShowAll((v) => !v)} className="px-2 text-[13px] text-muted hover:text-text cursor-pointer">
                  {showAll ? 'Show fewer' : `Show all ${trending.length} ›`}
                </button>
              )}
            </div>
          </>
        )}

        <Label className="mt-[22px]" hint="(optional)">
          Angle for the models
        </Label>
        <Textarea
          rows={2}
          value={state.description}
          onChange={(e) => patch({ description: e.target.value })}
          placeholder="Analyze decentralized finance vs traditional banking, environmental impact, stability, regulation."
          maxLength={4000}
          className="mt-2.5 resize-none"
        />
      </Card>

      <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]">
        <Card padding="none" className="p-5">
          <Label>Language</Label>
          <Select value={state.language} onChange={(e) => patch({ language: e.target.value })} className="mt-2.5" aria-label="Language">
            {!knownLanguage && <option value={state.language}>{state.language}</option>}
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </Select>
          <Hint>The models write and the voices speak in this language.</Hint>
        </Card>

        <Card padding="none" className="p-5">
          <Label>Rounds</Label>
          <Segmented grow className="mt-2.5" options={ROUND_OPTIONS} value={state.num_rounds} onChange={(num_rounds) => patch({ num_rounds })} />
          <div className="mt-2 font-mono text-[11px] text-dim">
            {state.num_rounds === 1 ? 'one argument each' : `opening · ${state.num_rounds > 2 ? `${state.num_rounds - 2}× rebuttal · ` : ''}closing`}
          </div>
        </Card>

        <Card padding="none" className="p-5">
          <Label>Reply length</Label>
          <Segmented
            grow
            size="sm"
            className="mt-2.5"
            options={LENGTH_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            value={state.length_preset}
            onChange={(length_preset) => patch({ length_preset })}
          />
          <div className="mt-2 font-mono text-[11px] text-dim">{lengthOption(state.length_preset).hint}</div>
        </Card>
      </div>
    </div>
  );
};
