import { ArrowRight, Globe } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getErrorMessage } from '../../api/client';
import { estimateDebate } from '../../api/debates';
import type { DebateConfig, Estimate, ModelInfo, PaymentsMode, VoiceInfo } from '../../api/types';
import { formatCost, formatMinutes, shortModelName } from '../../lib/format';
import { Card, ErrorBox, Hint, LinkButton, ModelIcon, SectionLabel, SpeakerBadge, Spinner, Stat } from '../ui';
import { languageLabel, lengthOption, speakerColorOf, speakerId, speakerTagOf, type WizardState } from './wizardState';

interface StepReviewProps {
  state: WizardState;
  config: DebateConfig;
  /** False while the model catalogue is still loading (config has empty model ids). */
  ready: boolean;
  models: ModelInfo[];
  voices: VoiceInfo[];
  ownKey: boolean;
  /** Changes when the balance changes so the estimate is refreshed after a top-up. */
  credits: number;
  paymentsMode: PaymentsMode;
  starting: boolean;
  startError: string | null;
  onStart: () => void;
  patch: (patch: Partial<WizardState>) => void;
}

const OUTPUT_LABELS: Record<string, string> = { audio: 'MP3', video: 'MP4', short: 'Short' };

export const StepReview = ({ state, config, ready, models, voices, ownKey, credits, paymentsMode, starting, startError, onStart, patch }: StepReviewProps) => {
  const [loaded, setLoaded] = useState<{ key: string; estimate: Estimate } | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  const configKey = JSON.stringify(config);
  const key = `${configKey}#${credits}#${attempt}`;

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      estimateDebate(JSON.parse(configKey) as DebateConfig)
        .then((estimate) => {
          if (!cancelled) setLoaded({ key, estimate });
        })
        .catch((err: unknown) => {
          if (!cancelled) setFailed({ key, message: getErrorMessage(err) });
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [ready, configKey, key]);

  const estimate = loaded?.key === key ? loaded.estimate : null;
  const estimateError = failed?.key === key ? failed.message : null;
  const estimating = ready && !estimate && !estimateError;

  const cost = estimate ? estimate.credits_cost_usd || estimate.llm_cost_usd + estimate.tts_cost_usd : null;
  const llmOnKey = Boolean(estimate?.own_key || ownKey);
  const voicesInCredits = Boolean(estimate && estimate.tts_cost_usd > 0 && !estimate.own_tts_key);
  const costLabel = llmOnKey
    ? voicesInCredits
      ? 'own key · voices in credits'
      : 'own key · $0 credits'
    : estimate?.own_tts_key
      ? 'models · voices on your key'
      : 'model + voice cost';
  const insufficient = Boolean(estimate && !estimate.sufficient);
  const canStart = ready && Boolean(estimate) && !insufficient && !starting;

  const settingsLine = [
    languageLabel(state.language),
    `${state.num_rounds} ${state.num_rounds === 1 ? 'round' : 'rounds'}`,
    `${lengthOption(state.length_preset).label.toLowerCase()} replies`,
    state.output_style === 'spoken' ? 'spoken' : 'written',
    state.outputs.length ? state.outputs.map((o) => OUTPUT_LABELS[o] ?? o).join(' + ') : 'text only',
    ...(config.media_plan?.visuals ? ['visual scenes'] : []),
    ...(config.media_plan?.visuals && config.media_plan.images === 'stock' && state.outputs.includes('audio') ? ['free photos'] : []),
    ...(config.media_plan?.visuals && config.media_plan.images === 'ai' && state.outputs.includes('audio') ? ['AI images'] : []),
    ...(config.fact_check ? ['fact-check'] : []),
  ].join(' · ');

  return (
    <div className="mt-[30px] grid gap-3.5 animate-rise [grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))]">
      <Card padding="lg">
        <SectionLabel>Topic</SectionLabel>
        <div className="mt-2 font-display text-[clamp(20px,2.2vw,26px)] font-bold leading-[1.2] tracking-[-0.02em] text-balance">{state.topic.trim()}</div>
        {state.description.trim() && <p className="mt-3 text-sm leading-relaxed text-muted">{state.description.trim()}</p>}
        <div className="mt-3 font-mono text-[11px] text-dim">{settingsLine}</div>
        <div className="mt-5 grid gap-3">
          {state.speakers.map((speaker, index) => {
            const color = speakerColorOf(state.speakers, index);
            const modelId = config.participants[index]?.model_id ?? '';
            const model = models.find((m) => m.id === modelId);
            const voiceId = config.media_plan?.voices[speakerId(index)];
            const voice = voices.find((v) => v.id === voiceId);
            return (
              <div key={speaker.key} className="flex items-center gap-3 rounded-field bg-ink px-3.5 py-3">
                <SpeakerBadge name={speaker.name} color={color} size={36} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold">
                    {speaker.name.trim()}
                    <span className="ml-1.5 font-mono text-[10px]" style={{ color }}>
                      {speakerTagOf(state.speakers, index)}
                    </span>
                  </div>
                  <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
                    {modelId && <ModelIcon modelId={modelId} size={12} className="text-text-3" />}
                    <span className="truncate">
                      {model?.name ?? (modelId ? shortModelName(modelId) : 'model pending')} · {voice?.name ?? voiceId ?? 'auto voice'}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <div className="grid content-start gap-3.5">
        <Card padding="lg">
          <SectionLabel>Estimate</SectionLabel>
          {estimateError ? (
            <ErrorBox className="mt-3">
              Could not estimate the cost: {estimateError}{' '}
              <button type="button" onClick={() => setAttempt((n) => n + 1)} className="font-semibold underline underline-offset-2 hover:text-text cursor-pointer">
                Retry
              </button>
            </ErrorBox>
          ) : (
            <div className="mt-3 grid grid-cols-2 gap-3" aria-busy={estimating}>
              <Stat value={cost !== null ? `~${formatCost(cost)}` : '…'} label={costLabel} />
              <Stat value={estimate ? `~${formatMinutes(estimate.duration_ms)}` : '…'} label="episode length" />
              <Stat value={estimate ? `${estimate.turns}` : '…'} label="turns" />
              <Stat value={estimate ? `~${formatMinutes(estimate.render_ms)}` : '…'} label="render time" />
            </div>
          )}
          {!ready && (
            <Hint className="mt-2 flex items-center gap-2">
              <Spinner className="size-3.5" /> Waiting for the model list…
            </Hint>
          )}
          {estimate && estimate.paid_models.length > 0 && !estimate.own_key && (
            <Hint className="mt-2">Paid models: {estimate.paid_models.map(shortModelName).join(', ')} — billed to your credits.</Hint>
          )}
          {estimate && (estimate.factcheck_cost_usd > 0 || estimate.images_cost_usd > 0) && (
            <Hint className="mt-2">
              Includes{' '}
              {[
                estimate.factcheck_cost_usd > 0 ? `fact-checks ~${formatCost(estimate.factcheck_cost_usd)}${estimate.own_key ? ' (on your key)' : ''}` : '',
                estimate.images_cost_usd > 0 ? `AI images ~${formatCost(estimate.images_cost_usd)}` : '',
              ]
                .filter(Boolean)
                .join(' and ')}
              .
            </Hint>
          )}
          <div className="mt-4 flex items-center justify-between rounded-field bg-ink px-3.5 py-3 text-[13px] text-text-3">
            <span>Credits after run</span>
            <span className={`font-mono ${estimate && estimate.credits_after !== null && estimate.credits_after < 0 ? 'text-con' : 'text-accent'}`}>
              {estimate && estimate.credits_after !== null ? `${estimate.credits_after < 0 ? '−' : ''}$${Math.abs(estimate.credits_after).toFixed(2)}` : estimating ? '…' : '—'}
            </span>
          </div>
        </Card>

        {insufficient && estimate && (
          <ErrorBox>
            <div>
              Not enough credits for this run — it needs about {formatCost(cost ?? 0)}
              {estimate.credits_before !== null ? ` and you have $${Math.max(0, estimate.credits_before).toFixed(2)}` : ''}. Top up, pick free models or add your own OpenRouter key in Account.
            </div>
            {paymentsMode !== 'disabled' && (
              <LinkButton to="/account" size="sm" className="mt-3">
                Top up credits
              </LinkButton>
            )}
          </ErrorBox>
        )}

        {startError && (
          <ErrorBox>
            <div>{startError}</div>
            <Link to="/account" className="mt-2 inline-block font-semibold text-accent hover:text-accent-hover">
              Go to account →
            </Link>
          </ErrorBox>
        )}

        <button
          type="button"
          role="switch"
          aria-checked={state.auto_publish}
          onClick={() => patch({ auto_publish: !state.auto_publish })}
          className="flex w-full items-start gap-3 rounded-panel border border-line-2 bg-surface p-4 text-left transition-colors hover:border-line-3 cursor-pointer"
        >
          <Globe className={`mt-0.5 size-4 shrink-0 ${state.auto_publish ? 'text-accent' : 'text-muted'}`} />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold">Publish to the gallery</span>
            <span className="mt-0.5 block text-xs leading-relaxed text-muted">
              {state.auto_publish
                ? 'Goes public with a share link once it finishes and passes an automatic content check.'
                : 'Stays private. You can still publish it later from the debate page.'}
            </span>
          </span>
          <span className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${state.auto_publish ? 'bg-accent' : 'bg-line-3'}`} aria-hidden="true">
            <span className={`absolute top-0.5 size-4 rounded-full bg-ink transition-[left] ${state.auto_publish ? 'left-[18px]' : 'left-0.5'}`} />
          </span>
        </button>

        <button
          type="button"
          onClick={onStart}
          disabled={!canStart}
          className="inline-flex w-full items-center justify-center gap-2 rounded-[16px] bg-accent p-[18px] font-display text-base font-extrabold tracking-[-0.01em] text-ink transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
        >
          {starting ? <Spinner className="size-4" /> : null}
          Start the debate <ArrowRight className="size-4" strokeWidth={2.5} />
        </button>
        <div className="text-center text-xs leading-relaxed text-dim">Runs in your browser. You'll be notified when the video is ready.</div>
      </div>
    </div>
  );
};
