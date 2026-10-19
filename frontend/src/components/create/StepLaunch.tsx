import { ArrowLeft, ArrowRight, ArrowUpRight, Check, Globe, KeyRound, PenTool, SearchCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { DebateConfig, Estimate, ImageSource, PaymentsMode, VoiceInfo } from '../../api/types';
import { detectStyle } from '../../data/styles';
import type { TtsKeyCheck, TtsKeyStatus } from '../../hooks/useElevenLabsKeyStatus';
import { estimateCost } from '../../hooks/useEstimate';
import { useSiteStatus } from '../../hooks/useSiteStatus';
import { formatAge, formatCost, formatMinutes, shortModelName } from '../../lib/format';
import { flowById, formatSpec } from '../../lib/formats';
import { accountPath } from '../account/tabs';
import { ErrorBox, Hint, ModelIcon, Spinner, SwitchTrack } from '../ui';
import { Favicon } from './TrendingBrowser';
import { OUTPUT_OPTIONS, QUALITY_OPTIONS, languageLabel, lengthOption, speakerColorOf, speakerId, speakerTagOf, type WizardState, type WizardStep } from './wizardState';

interface StepLaunchProps {
  state: WizardState;
  patch: (patch: Partial<WizardState>) => void;
  config: DebateConfig;
  /** False while the model catalogue is still loading (config has empty model ids). */
  ready: boolean;
  /** On-stage name of every speaker. */
  names: string[];
  voices: VoiceInfo[];
  estimate: { estimate: Estimate | null; shown: Estimate | null; error: string | null; estimating: boolean; retry: () => void };
  ownKey: boolean;
  paymentsMode: PaymentsMode;
  /** Masked key already stored on the account, if any. */
  accountKeyMasked: string | null;
  /** Browser-only keys (lib/localKeys), managed on the Account page. */
  openrouterKey: string;
  /** The browser's ElevenLabs key, as checked against ElevenLabs. */
  ttsKeyCheck: TtsKeyCheck;
  /** Why the format cannot run (no balance or key for its voices); blocks the start. */
  formatLock: string | null;
  /** No balance: AI pictures (system key) are locked. */
  aiImagesLocked: boolean;
  /** No balance and no own OpenRouter key: the paid fact-check is locked. */
  factCheckLocked: boolean;
  starting: boolean;
  startError: string | null;
  onStart: () => void;
  goTo: (step: WizardStep) => void;
}

const OUTPUT_LABELS: Record<string, string> = { audio: 'MP3', video: 'MP4', short: 'Short' };

const TTS_KEY_LABELS: Record<TtsKeyStatus, string | null> = {
  none: null,
  checking: 'checking…',
  valid: 'set in this browser',
  invalid: 'rejected by ElevenLabs',
  unknown: 'set in this browser',
};

const Panel = ({ title, hint, right, className = '', children }: { title: string; hint?: string; right?: ReactNode; className?: string; children: ReactNode }) => (
  <section className={`grid gap-3.5 rounded-panel border border-line bg-surface p-[clamp(16px,2vw,22px)] ${className}`}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="font-display text-lg font-bold tracking-[-0.02em]">{title}</h2>
      {hint && <span className="text-xs text-dim">{hint}</span>}
      {right}
    </div>
    {children}
  </section>
);

/** White-on-dark segmented control of the design (video quality); the pictures one is accent. */
const Segment = <T extends string>({ value, options, onChange, accent = false, disabled = false }: { value: T; options: { value: T; label: string; disabled?: boolean }[]; onChange: (v: T) => void; accent?: boolean; disabled?: boolean }) => (
  <div className={`flex gap-[3px] rounded-[10px] border border-white/8 bg-ink p-[3px] ${disabled ? 'opacity-40' : ''}`} role="tablist">
    {options.map((o) => (
      <button
        key={o.value}
        type="button"
        role="tab"
        aria-selected={value === o.value}
        disabled={disabled || o.disabled}
        onClick={() => onChange(o.value)}
        className={`whitespace-nowrap rounded-[7px] px-[11px] py-1.5 text-xs font-semibold transition-colors cursor-pointer disabled:cursor-not-allowed ${
          value === o.value ? (accent ? 'bg-accent text-ink' : 'bg-text text-ink') : 'text-muted enabled:hover:text-text disabled:opacity-50'
        }`}
      >
        {o.label}
      </button>
    ))}
  </div>
);

const FeatureRow = ({
  icon,
  title,
  cost,
  text,
  on,
  disabled = false,
  divider = false,
  onToggle,
  children,
}: {
  icon: ReactNode;
  title: string;
  cost: string;
  text: string;
  on: boolean;
  disabled?: boolean;
  divider?: boolean;
  onToggle: () => void;
  children?: ReactNode;
}) => (
  <div className={`grid gap-3.5 py-4 ${divider ? 'border-t border-white/6' : ''}`}>
    <button type="button" role="switch" aria-checked={on} disabled={disabled} onClick={onToggle} className="flex items-start gap-3.5 text-left cursor-pointer disabled:cursor-not-allowed">
      <span className={`grid size-[38px] shrink-0 place-items-center rounded-[11px] transition-colors ${on ? 'bg-accent/10 text-accent' : 'bg-surface-2 text-muted'}`}>{icon}</span>
      <span className={`min-w-0 flex-1 ${disabled ? 'opacity-60' : ''}`}>
        <span className="flex flex-wrap items-center gap-2.5">
          <span className="text-[15px] font-bold">{title}</span>
          <span className="rounded-[5px] bg-surface-2 px-[7px] py-0.5 font-mono text-[10px] text-text-3">{cost}</span>
        </span>
        <span className="mt-1 block text-[13px] leading-normal text-muted text-pretty">{text}</span>
      </span>
      <SwitchTrack on={on} className={disabled ? 'opacity-60' : ''} />
    </button>
    {children}
  </div>
);

const KeyStatus = ({ label, value, bad = false, title }: { label: string; value: string | null; bad?: boolean; title?: string }) => (
  <span title={title} className="inline-flex items-center gap-1.5 rounded-full border border-white/8 bg-ink px-2.5 py-1 text-xs font-semibold">
    <span className={`size-1.5 rounded-full ${bad ? 'bg-con' : value ? 'bg-ok' : 'bg-dim'}`} aria-hidden="true" />
    {label}
    <span className="font-normal text-dim">{value ?? 'not set'}</span>
  </span>
);

const PanelLabel = ({ children, onEdit }: { children: string; onEdit: () => void }) => (
  <div className="flex items-center justify-between">
    <span className="font-mono text-[10px] tracking-[0.1em] text-muted">{children}</span>
    <button type="button" onClick={onEdit} className="text-xs font-semibold text-muted hover:text-accent cursor-pointer">
      Edit
    </button>
  </div>
);

/** Step 3: writing style, outputs, scenes and keys on the left; summary, estimate and start on the right. */
export const StepLaunch = ({
  state,
  patch,
  config,
  ready,
  names,
  voices,
  estimate: est,
  ownKey,
  paymentsMode,
  accountKeyMasked,
  openrouterKey,
  ttsKeyCheck,
  formatLock,
  aiImagesLocked,
  factCheckLocked,
  starting,
  startError,
  onStart,
  goTo,
}: StepLaunchProps) => {
  const site = useSiteStatus();
  const spec = formatSpec(state.format);
  // A premium-only format always builds its audio (the wizard locks that output on).
  const outputLocked = (value: WizardState['outputs'][number]) => spec.premiumOnly && value === 'audio';
  const toggleOutput = (value: WizardState['outputs'][number]) =>
    !outputLocked(value) &&
    patch({
      outputs: state.outputs.includes(value)
        ? state.outputs.filter((o) => o !== value)
        : OUTPUT_OPTIONS.map((o) => o.value).filter((o) => o === value || state.outputs.includes(o)),
    });

  const withAudio = state.outputs.includes('audio');
  const withVideo = state.outputs.includes('video') || state.outputs.includes('short');
  const visualsOn = spec.visuals && state.visuals;
  const images: ImageSource = withAudio && !(state.images === 'ai' && aiImagesLocked) ? state.images : 'off';
  const factCheckOn = visualsOn && state.fact_check && !factCheckLocked;

  const { estimate, shown, error: estimateError, estimating } = est;
  const cost = shown ? estimateCost(shown) : null;
  const llmOnKey = Boolean(shown?.own_key || ownKey);
  const music = Boolean(shown && shown.music_ms > 0);
  const voicesInCredits = Boolean(shown && shown.tts_cost_usd + shown.music_cost_usd > 0 && !shown.own_tts_key);
  const sound = music ? 'music' : 'voices';
  const costLabel = llmOnKey
    ? voicesInCredits
      ? `own key · ${sound} in credits`
      : 'own key · $0 credits'
    : shown?.own_tts_key
      ? `models · ${sound} on your key`
      : cost === 0
        ? 'free models + voices'
        : music
          ? 'models + music + voices'
          : 'model + voice cost';
  const insufficient = Boolean(estimate && !estimate.sufficient);
  // A debate on free models over their limits (too big, or none left today).
  const freeLimit = estimate?.free_limit ?? null;
  const freeRuns = shown?.free_runs ?? null;
  const paused = site.maintenance;
  const canStart = ready && Boolean(estimate) && !insufficient && !freeLimit && !formatLock && !starting && !paused && state.topic.trim().length > 0;
  const after = shown?.credits_after ?? null;

  const meta = [
    ...(spec.id === 'debate' ? [] : [spec.name.toLowerCase()]),
    languageLabel(state.language),
    `${state.num_rounds} ${state.num_rounds === 1 ? 'round' : 'rounds'}`,
    spec.music ? spec.lengthHints[state.length_preset] : `${lengthOption(state.length_preset).label.toLowerCase()} replies`,
    ...(spec.outputStyle ? [] : [state.output_style === 'spoken' ? 'spoken' : 'written']),
    state.outputs.length ? state.outputs.map((o) => OUTPUT_LABELS[o] ?? o).join(' + ') : 'text only',
    ...(config.media_plan?.visuals ? ['scenes'] : []),
    ...(config.media_plan?.visuals && config.media_plan.images === 'stock' ? ['free photos'] : []),
    ...(config.media_plan?.visuals && config.media_plan.images === 'ai' ? ['AI images'] : []),
    ...(config.fact_check ? ['fact-check'] : []),
  ];
  const news = config.news;

  return (
    <div className="mt-7 grid items-start gap-[22px] animate-rise min-[1180px]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div className="grid min-w-0 gap-3.5">
        {/* A format that writes in its own style (the battle's verses) has nothing to choose. */}
        {!spec.outputStyle && (
          <Panel title="Writing style" hint="How the models phrase their turns">
            <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr))]">
              {(
                [
                  { value: 'spoken', label: 'Spoken', tag: 'BEST FOR VIDEO', text: 'Short quotable sentences, no lists or headers. Sounds natural in voice.' },
                  { value: 'markdown', label: 'Written', tag: '', text: 'Structured prose with headings. Best for reading and Markdown export.' },
                ] as const
              ).map((o) => {
                const on = state.output_style === o.value;
                return (
                  <button
                    key={o.value}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    onClick={() => patch({ output_style: o.value })}
                    className={`flex items-start gap-3 rounded-[14px] border px-4 py-3.5 text-left transition-colors cursor-pointer ${on ? 'border-accent bg-accent/5' : 'border-white/8 bg-ink hover:border-line-3'}`}
                  >
                    <span className={`mt-px grid size-[18px] shrink-0 place-items-center rounded-full border-2 ${on ? 'border-accent' : 'border-[#3a3f4d]'}`}>
                      <span className={`size-2 rounded-full ${on ? 'bg-accent' : ''}`} />
                    </span>
                    <span>
                      <span className="text-sm font-bold">
                        {o.label}
                        {o.tag && <span className="ml-2 font-mono text-[10px] tracking-[0.06em] text-accent">{o.tag}</span>}
                      </span>
                      <span className="mt-[3px] block text-[12.5px] leading-[1.45] text-muted">{o.text}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </Panel>
        )}

        <Panel
          title="Outputs"
          right={
            <div className="flex items-center gap-2.5">
              <span className={`text-xs text-muted ${withVideo ? '' : 'opacity-40'}`}>Video quality</span>
              <Segment value={state.quality} options={QUALITY_OPTIONS} onChange={(quality) => patch({ quality })} disabled={!withVideo} />
            </div>
          }
        >
          <div className="grid gap-2.5 sm:grid-cols-3">
            {OUTPUT_OPTIONS.map((o) => {
              const on = state.outputs.includes(o.value);
              const locked = outputLocked(o.value);
              const quality = QUALITY_OPTIONS.find((q) => q.value === state.quality)?.label ?? state.quality;
              const text = o.value === 'video' ? `16:9 · ${quality} · captions` : locked && spec.music ? 'MP3 · beat + verses' : o.text;
              return (
                <button
                  key={o.value}
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  aria-disabled={locked}
                  title={locked ? `A ${spec.name.toLowerCase()} is always voiced: its audio is the show` : undefined}
                  onClick={() => toggleOutput(o.value)}
                  className={`flex items-center gap-3 rounded-[14px] border p-3.5 text-left transition-colors ${locked ? 'cursor-default' : 'cursor-pointer'} ${
                    on ? 'border-accent/55 bg-accent/5' : 'border-white/8 bg-ink hover:border-line-3'
                  }`}
                >
                  <span className="grid size-10 shrink-0 place-items-center rounded-[11px] bg-surface-2">
                    <span className="rounded-[4px] transition-opacity" style={{ width: o.icon.w, height: o.icon.h, background: o.icon.color, opacity: on ? 1 : 0.35 }} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-bold">{o.label}</span>
                    <span className="mt-0.5 block text-xs text-muted">{text}</span>
                  </span>
                  <span className={`grid size-5 shrink-0 place-items-center rounded-md border text-ink ${on ? 'border-accent bg-accent' : 'border-white/20'}`}>{on && <Check className="size-[13px]" strokeWidth={3} />}</span>
                </button>
              );
            })}
          </div>
          {state.outputs.length === 0 && <Hint className="mt-0">No outputs selected — the debate runs as text only; you can build audio and video later.</Hint>}
        </Panel>

        {/* Charts, sketches and fact-checks only where the format has scenes. */}
        {spec.visuals && (
          <section className="grid rounded-panel border border-line bg-surface px-[clamp(16px,2vw,22px)] py-1.5">
            <FeatureRow
              icon={<PenTool className="size-[18px]" />}
              title="Visual scenes"
              cost={images === 'ai' ? '~$0.01 / image' : 'FREE'}
              text="Charts, numbers and sketches appear next to each turn and in the video exactly when they are said. Debaters can ask for visuals and challenge each other's figures."
              on={visualsOn}
              onToggle={() => patch({ visuals: !state.visuals })}
            >
              {visualsOn && (
                <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2.5 sm:ml-[52px]">
                  <span className="text-xs text-muted">Pictures</span>
                  <Segment
                    accent
                    value={images}
                    onChange={(value) => patch({ images: value })}
                    options={[
                      { value: 'off', label: 'None' },
                      { value: 'stock', label: 'Free photos', disabled: !withAudio },
                      { value: 'ai', label: 'AI images', disabled: !withAudio || aiImagesLocked },
                    ]}
                  />
                  <span className="text-xs text-dim">
                    {!withAudio
                      ? 'Pictures are found while the audio is built — select Audio to add them.'
                      : images === 'ai'
                        ? 'Generated for scenes that show a real place or thing, from your balance; checked before use.'
                        : images === 'stock'
                          ? 'Freely licensed photos from Wikimedia Commons, credited in the frame.'
                          : aiImagesLocked
                            ? 'Only charts and drawings. AI images need a balance.'
                            : 'Only charts and drawings.'}
                  </span>
                </div>
              )}
            </FeatureRow>
            <FeatureRow
              icon={<SearchCheck className="size-[18px]" />}
              title="Fact-check figures"
              cost="~$0.006 / check"
              text={
                !visualsOn
                  ? 'Checks the figures and quotes of the visual scenes — turn the scenes on first.'
                  : factCheckLocked
                    ? 'A web search checks the figures on screen; it is paid from your balance or your OpenRouter key.'
                    : 'A web search checks the figures and quotes shown on screen. Opponents and the judge see the results.'
              }
              on={factCheckOn}
              disabled={!visualsOn || factCheckLocked}
              divider
              onToggle={() => patch({ fact_check: !state.fact_check })}
            />
          </section>
        )}

        <section className="flex flex-wrap items-center gap-3.5 rounded-panel border border-line bg-surface p-[clamp(16px,2vw,22px)]">
          <span className="grid size-[38px] shrink-0 place-items-center rounded-[11px] bg-surface-2 text-text-3">
            <KeyRound className="size-[18px]" />
          </span>
          <div className="min-w-0 flex-[1_1_260px]">
            <div className="text-[15px] font-bold">
              Your own API keys <span className="text-[13px] font-normal text-dim">optional</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <KeyStatus label="OpenRouter" value={openrouterKey ? 'set in this browser' : accountKeyMasked ? `account key ${accountKeyMasked}` : null} />
              <KeyStatus label="ElevenLabs" value={TTS_KEY_LABELS[ttsKeyCheck.status]} bad={ttsKeyCheck.status === 'invalid'} title={ttsKeyCheck.error ?? undefined} />
            </div>
          </div>
          {/* New tab: the wizard keeps its state and picks the keys up when they change. */}
          <a
            href={accountPath('keys')}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-[38px] items-center gap-2 rounded-[11px] border border-line-2 bg-surface-2 px-3.5 text-[13px] font-semibold transition-colors hover:bg-surface-3"
          >
            Manage keys <ArrowUpRight className="size-3.5" />
          </a>
        </section>

        <button
          type="button"
          onClick={() => goTo(2)}
          className="inline-flex h-[42px] items-center gap-2 justify-self-start rounded-field border border-white/8 bg-surface px-[18px] text-sm font-semibold transition-colors hover:bg-surface-2 cursor-pointer"
        >
          <ArrowLeft className="size-4" /> Back to speakers
        </button>
      </div>

      <aside className="grid min-w-0 gap-[18px] rounded-[22px] border border-white/9 bg-surface p-5 min-[1180px]:sticky min-[1180px]:top-5">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-[19px] font-bold tracking-[-0.02em]">Ready to run</h2>
          <span className="font-mono text-[10px] tracking-[0.08em] text-dim">STEP 3 OF 3</span>
        </div>

        <div className="grid gap-2.5">
          <PanelLabel onEdit={() => goTo(1)}>TOPIC</PanelLabel>
          <div className={`font-display text-[clamp(19px,1.7vw,23px)] font-bold leading-[1.18] tracking-[-0.02em] text-balance ${state.topic.trim() ? '' : 'text-dim'}`}>
            {state.topic.trim() || 'No topic yet — pick one in step 1'}
          </div>
          {news && (
            <div className="flex items-center gap-2 text-xs text-muted">
              <Favicon url={news.url} />
              Grounded in {news.outlet || 'the news story'}
              {news.published_at ? ` · ${formatAge(news.published_at)} ago` : ''}
            </div>
          )}
          <div className="flex flex-wrap gap-1.5">
            {meta.map((m) => (
              <span key={m} className="rounded-[7px] border border-line bg-ink px-[9px] py-1 font-mono text-[11px] text-text-3">
                {m}
              </span>
            ))}
          </div>
        </div>

        <div className="grid gap-2.5">
          <PanelLabel onEdit={() => goTo(2)}>LINEUP</PanelLabel>
          <div className="grid gap-1.5">
            {state.speakers.map((speaker, index) => {
              const color = speakerColorOf(state.speakers, index);
              const modelId = config.participants[index]?.model_id ?? '';
              const voiceId = config.media_plan?.voices[speakerId(index)];
              const voice = voices.find((v) => v.id === voiceId);
              // Rappers of a generated track take a flow instead of a voice.
              const flow = flowById(config.media_plan?.flows?.[speakerId(index)]);
              return (
                <div key={speaker.key} className="flex items-center gap-3 rounded-field bg-ink px-2.5 py-[9px]">
                  <span className="grid size-[34px] shrink-0 place-items-center rounded-[10px] border bg-surface text-text" style={{ borderColor: color }}>
                    {modelId && <ModelIcon modelId={modelId} size={19} />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-bold">{names[index]}</span>
                      <span className="shrink-0 font-mono text-[10px] tracking-[0.08em]" style={{ color }}>
                        {speakerTagOf(state.speakers, index, spec)}
                      </span>
                    </span>
                    <span className="block truncate text-xs text-muted" title={modelId ? shortModelName(modelId) : undefined}>
                      {flow ? flow.label : (voice?.name ?? (voiceId ? voiceId : 'auto voice'))} · {detectStyle(speaker.prompt)?.full ?? 'Custom'}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="grid gap-3 rounded-[16px] border border-white/6 bg-ink p-4">
          {estimateError ? (
            <ErrorBox>
              Could not estimate the cost: {estimateError}{' '}
              <button type="button" onClick={est.retry} className="font-semibold underline underline-offset-2 hover:text-text cursor-pointer">
                Retry
              </button>
            </ErrorBox>
          ) : (
            <div className="grid grid-cols-2 gap-x-3 gap-y-3.5" aria-busy={estimating}>
              {[
                { value: cost === null ? '…' : cost === 0 ? '$0.00' : `~${formatCost(cost)}`, label: costLabel },
                { value: shown ? `~${formatMinutes(shown.duration_ms)}` : '…', label: 'episode length' },
                { value: shown ? String(shown.turns) : '…', label: 'turns' },
                { value: !withVideo ? '—' : shown ? `~${formatMinutes(shown.render_ms)}` : '…', label: 'render time' },
              ].map((s) => (
                <div key={s.label}>
                  <div className="font-display text-2xl font-bold leading-[1.1] tracking-[-0.02em]">{s.value}</div>
                  <div className="mt-0.5 text-xs text-muted">{s.label}</div>
                </div>
              ))}
            </div>
          )}
          {!ready && (
            <Hint className="mt-0 flex items-center gap-2">
              <Spinner className="size-3.5" /> Waiting for the model list…
            </Hint>
          )}
          {shown && shown.paid_models.length > 0 && !shown.own_key && <Hint className="mt-0">Paid models: {shown.paid_models.map(shortModelName).join(', ')} — billed to your credits.</Hint>}
          {shown && music && (
            <Hint className="mt-0">
              Includes ~{formatMinutes(shown.music_ms)} of music
              {shown.own_tts_key ? ' on your ElevenLabs key' : ` ~${formatCost(shown.music_cost_usd)} and the ${spec.hostLabel}'s and the judge's voices ~${formatCost(shown.tts_cost_usd)}`}. A
              rebuild with the same verses reuses the track.
            </Hint>
          )}
          {shown && (shown.factcheck_cost_usd > 0 || shown.images_cost_usd > 0) && (
            <Hint className="mt-0">
              Includes{' '}
              {[
                shown.factcheck_cost_usd > 0 ? `fact-checks ~${formatCost(shown.factcheck_cost_usd)}${shown.own_key ? ' (on your key)' : ''}` : '',
                shown.images_cost_usd > 0 ? `AI images ~${formatCost(shown.images_cost_usd)}` : '',
              ]
                .filter(Boolean)
                .join(' and ')}
              .
            </Hint>
          )}
          <div className="h-px bg-white/6" />
          <div className="flex items-center justify-between text-[13px] text-text-3">
            <span>Credits after run</span>
            <span className={`font-mono ${after !== null && after < 0 ? 'text-con' : 'text-accent'}`}>
              {after !== null ? `${after < 0 ? '−' : ''}$${Math.abs(after).toFixed(2)}` : estimating ? '…' : '—'}
            </span>
          </div>
          {freeRuns && (
            <div className="flex items-center justify-between text-[13px] text-text-3">
              <span>Free debates, last 24 h</span>
              <span className={`font-mono ${freeRuns.left > 0 ? 'text-accent' : 'text-con'}`}>
                {freeRuns.left} of {freeRuns.per_day} left
              </span>
            </div>
          )}
          {freeLimit && (
            <div className="flex items-center justify-between gap-2.5 rounded-[10px] border border-con/25 bg-con/8 px-3 py-2.5 text-xs text-[#ffb3a6]">
              <span>{freeLimit}</span>
              <Link to={accountPath('keys')} className="shrink-0 font-bold text-con hover:text-text">
                Add a key
              </Link>
            </div>
          )}
          {formatLock && (
            <div className="flex items-center justify-between gap-2.5 rounded-[10px] border border-con/25 bg-con/8 px-3 py-2.5 text-xs text-[#ffb3a6]">
              <span>{formatLock}</span>
              <Link to={accountPath(paymentsMode !== 'disabled' ? 'billing' : 'keys')} className="shrink-0 font-bold text-con hover:text-text">
                {paymentsMode !== 'disabled' ? 'Top up' : 'Add a key'}
              </Link>
            </div>
          )}
          {insufficient && estimate && !formatLock && (
            <div className="flex items-center justify-between gap-2.5 rounded-[10px] border border-con/25 bg-con/8 px-3 py-2.5 text-xs text-[#ffb3a6]">
              <span>
                Not enough credits for these settings — about {formatCost(cost ?? 0)}
                {estimate.credits_before !== null ? `, you have $${Math.max(0, estimate.credits_before).toFixed(2)}` : ''}.{' '}
                {estimate.music_cost_usd > 0
                  ? 'Pick free models, shorter verses or fewer rounds, or bring your own keys (ElevenLabs on a paid plan).'
                  : 'Pick free models or add your own OpenRouter key.'}
              </span>
              {paymentsMode !== 'disabled' && (
                <Link to={accountPath('billing')} className="shrink-0 font-bold text-con hover:text-text">
                  Top up
                </Link>
              )}
            </div>
          )}
        </div>

        <button type="button" role="switch" aria-checked={state.auto_publish} onClick={() => patch({ auto_publish: !state.auto_publish })} className="flex items-center gap-3 text-left cursor-pointer">
          <span className={`grid size-[34px] shrink-0 place-items-center rounded-[10px] bg-surface-2 ${state.auto_publish ? 'text-accent' : 'text-text-3'}`}>
            <Globe className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold">Publish to the gallery</span>
            <span className="mt-0.5 block text-xs text-muted">
              {state.auto_publish ? 'Public with a share link after an automatic content check.' : 'Stays private. You can still publish it later from the debate page.'}
            </span>
          </span>
          <SwitchTrack on={state.auto_publish} />
        </button>

        {startError && (
          <ErrorBox>
            <div>{startError}</div>
            <Link to="/account" className="mt-2 inline-block font-semibold text-accent hover:text-accent-hover">
              Go to account →
            </Link>
          </ErrorBox>
        )}

        <div className="grid gap-2">
          <button
            type="button"
            onClick={onStart}
            disabled={!canStart}
            className={`flex h-14 items-center justify-center gap-2.5 rounded-[16px] font-display text-[17px] font-extrabold tracking-[-0.01em] transition-[filter,background-color] ${
              canStart ? 'bg-accent text-ink shadow-[0_20px_40px_-18px_rgba(217,255,61,0.55)] hover:brightness-106 cursor-pointer' : 'cursor-not-allowed bg-surface-3 text-dim'
            }`}
          >
            {starting && <Spinner className="size-4" />}
            Start the {spec.show} <ArrowRight className="size-4" strokeWidth={2.5} />
          </button>
          <div className={`text-center text-xs ${paused ? 'text-host' : 'text-dim'}`}>
            {paused ? site.maintenance_message : 'Runs on our servers; the video renders in your browser when you export it.'}
          </div>
        </div>
      </aside>
    </div>
  );
};
