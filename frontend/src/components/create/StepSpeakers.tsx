import { ArrowUpRight, Lock, Plus } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import type { BillingConfig, ModelInfo, TTSProviderName } from '../../api/types';
import { useLeaderboard } from '../../hooks/useLeaderboard';
import type { VoiceCatalogue } from '../../hooks/useVoices';
import { accountPath, type AccountTab } from '../account/tabs';
import { ErrorBox, Hint, Spinner } from '../ui';
import { ROW_COLUMNS, SpeakerRow } from './SpeakerRow';
import {
  MAX_DEBATERS,
  MIN_DEBATERS,
  countDebaters,
  defaultDebater,
  reindexVoices,
  speakerColorOf,
  speakerId,
  speakerNamesOf,
  speakerTagOf,
  type Speaker,
  type WizardState,
} from './wizardState';

interface StepSpeakersProps {
  state: WizardState;
  patch: (patch: Partial<WizardState>) => void;
  models: ModelInfo[];
  modelsLoading: boolean;
  modelsError: string | null;
  defaultModelId: string;
  catalogue: VoiceCatalogue;
  /** Effective voice per speaker id (see resolveVoices). */
  resolvedVoices: Record<string, string>;
  /** Effective voice engine (premium falls back to Edge when it is not available). */
  provider: TTSProviderName;
  billing: BillingConfig;
  /** User's own working ElevenLabs key (lib/localKeys) — premium voices without credits. */
  hasTtsKey: boolean;
  /** Why ElevenLabs rejected the key saved in this browser, if it did. */
  ttsKeyError: string | null;
  /** Empty balance and no own ElevenLabs key, so premium voices cannot be picked. */
  premiumLocked: boolean;
  paidLocked: boolean;
  showErrors: boolean;
}

/** Voice engine pill: name + price tag (the description goes to the tooltip). */
const EngineOption = ({
  active,
  disabled = false,
  onClick,
  title,
  tag,
  tooltip,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  title: string;
  tag: ReactNode;
  tooltip: string;
}) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    aria-pressed={active}
    title={tooltip}
    className={`flex flex-col items-start gap-0.5 rounded-[11px] border px-3.5 py-2 text-[13px] font-semibold transition-colors sm:inline-flex sm:h-10 sm:flex-row sm:items-center sm:gap-2.5 sm:py-0 ${
      active ? 'border-accent bg-accent/6 text-text' : 'border-white/8 bg-ink text-text hover:border-line-3'
    } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
  >
    {title}
    <span className="font-mono text-[11px] font-normal text-accent">{tag}</span>
  </button>
);

/** Section heading of the step: title, optional counter and a hint on the right. */
const SectionHead = ({ title, count, hint }: { title: string; count?: string; hint: string }) => (
  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-1">
    <div className="flex items-baseline gap-2.5">
      <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{title}</h2>
      {count && <span className="font-mono text-xs text-muted">{count}</span>}
    </div>
    <span className="text-xs text-dim">{hint}</span>
  </div>
);

/** Account page in a new tab: the wizard keeps its state and picks up new keys immediately. */
const AccountLink = ({ children, tab }: { children: string; tab?: AccountTab }) => (
  <a href={accountPath(tab)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-accent hover:text-accent-hover">
    {children}
    <ArrowUpRight className="size-3" />
  </a>
);

export const StepSpeakers = ({
  state,
  patch,
  models,
  modelsLoading,
  modelsError,
  defaultModelId,
  catalogue,
  resolvedVoices,
  provider,
  billing,
  hasTtsKey,
  ttsKeyError,
  premiumLocked,
  paidLocked,
  showErrors,
}: StepSpeakersProps) => {
  const debaters = countDebaters(state.speakers);
  const names = speakerNamesOf(state.speakers, models, defaultModelId);
  // Speaker whose system prompt editor is open.
  const [expanded, setExpanded] = useState<string | null>(null);
  const premiumAvailable = billing.elevenlabs_available || hasTtsKey;
  // Without a catalogue the server assigns the voices, so there is nothing to pick.
  const voicesAuto = Boolean(catalogue.error);
  // Voice ids are provider-specific: switching the engine drops the explicit choices.
  const setProvider = (next: TTSProviderName) => {
    if (next !== state.provider) patch({ provider: next, voices: {} });
  };
  const takenBy = (index: number) =>
    Object.fromEntries(
      state.speakers.flatMap((_, i) => {
        const voice = resolvedVoices[speakerId(i)];
        return i !== index && voice ? [[voice, names[i] || speakerTagOf(state.speakers, i)]] : [];
      }),
    );
  const { data: leaderboard } = useLeaderboard();
  const voiceLanguage = { code: catalogue.language, name: state.language.trim() || 'English' };
  // ElevenLabs lists library voices for the language only on paid plans: say why there are none.
  const noNativeVoices =
    provider === 'elevenlabs' &&
    !catalogue.loading &&
    catalogue.voices.length > 0 &&
    !!catalogue.language &&
    catalogue.language !== 'en' &&
    !catalogue.voices.some((v) => v.languages.includes(catalogue.language));
  const ranks = Object.fromEntries((leaderboard?.entries ?? []).map((e, i) => [e.model_id, i + 1]));

  const updateSpeaker = (index: number, changes: Partial<Speaker>) =>
    patch({ speakers: state.speakers.map((s, i) => (i === index ? { ...s, ...changes } : s)) });

  const setVoice = (index: number, voiceId: string) => patch({ voices: { ...state.voices, [speakerId(index)]: voiceId } });

  const addSpeaker = () => {
    if (debaters >= MAX_DEBATERS) return;
    patch({ speakers: [...state.speakers, defaultDebater(debaters)] });
  };

  const removeSpeaker = (index: number) => {
    if (state.speakers[index].role !== 'debater' || debaters <= MIN_DEBATERS) return;
    patch({ speakers: state.speakers.filter((_, i) => i !== index), voices: reindexVoices(state.voices, index) });
  };

  const row = (speaker: Speaker) => {
    const index = state.speakers.indexOf(speaker);
    return (
      <SpeakerRow
        key={speaker.key}
        speaker={speaker}
        name={names[index]}
        color={speakerColorOf(state.speakers, index)}
        tag={speakerTagOf(state.speakers, index)}
        modelId={speaker.model_id || defaultModelId}
        voiceId={resolvedVoices[speakerId(index)] ?? ''}
        models={models}
        modelsLoading={modelsLoading}
        paidLocked={paidLocked}
        ranks={ranks}
        voices={catalogue.voices}
        voicesLoading={catalogue.loading}
        voicesAuto={voicesAuto}
        voicesTakenBy={takenBy(index)}
        showVoiceLanguages={provider === 'elevenlabs'}
        voiceLanguage={voiceLanguage}
        expanded={expanded === speaker.key}
        removable={speaker.role === 'debater' && debaters > MIN_DEBATERS}
        showErrors={showErrors}
        onChange={(changes) => updateSpeaker(index, changes)}
        onVoice={(voiceId) => setVoice(index, voiceId)}
        onToggleExpanded={() => setExpanded((key) => (key === speaker.key ? null : speaker.key))}
        onRemove={() => removeSpeaker(index)}
      />
    );
  };
  const slotsLeft = MAX_DEBATERS - debaters;

  return (
    <div className="mt-7 grid gap-[22px] animate-rise">
      <div className="text-sm text-muted">Cast the speakers. Each gets a model, a voice and a persona.</div>

      {(modelsError || paidLocked) && (
        <div className="-mt-2 grid gap-2">
          {modelsError && <ErrorBox>Could not load the model list: {modelsError}</ErrorBox>}
          {paidLocked && (
            <Hint className="mt-0">
              Paid models are locked: add credits or your own OpenRouter key in <AccountLink>Account</AccountLink>. Free models work right away.
            </Hint>
          )}
        </div>
      )}

      <div className="rounded-card border border-line bg-surface px-3.5 py-3">
        {/* Phones: label and key link on top, the two engines side by side below. */}
        <div className="grid gap-2.5 sm:flex sm:flex-wrap sm:items-center sm:gap-x-3.5">
          <div className="flex items-center justify-between gap-3 px-1 sm:contents">
            <span className="text-[13px] font-semibold text-text-3 sm:pl-1">Voice engine</span>
            <span className="text-xs text-muted sm:order-last sm:ml-auto">
              Own ElevenLabs key? <AccountLink tab="keys">Account</AccountLink>
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:contents">
            <EngineOption active={provider === 'edge'} onClick={() => setProvider('edge')} title="Edge neural" tag="FREE" tooltip="Good quality, word timestamps, instant." />
            <EngineOption
              active={provider === 'elevenlabs'}
              onClick={() => setProvider('elevenlabs')}
              disabled={!premiumAvailable || premiumLocked}
              title="Premium neural"
              tag={
                hasTtsKey ? (
                  'YOUR KEY'
                ) : premiumLocked ? (
                  <span className="inline-flex items-center gap-1 text-muted">
                    <Lock className="size-3" /> ${billing.tts_price_per_min.toFixed(2)}/min
                  </span>
                ) : (
                  `$${billing.tts_price_per_min.toFixed(2)}/min`
                )
              }
              tooltip={
                !premiumAvailable
                  ? 'Premium voices are not configured on this server — add your own ElevenLabs key in Account'
                  : premiumLocked
                    ? 'Top up credits to unlock premium voices, or add your own ElevenLabs key in Account'
                    : 'ElevenLabs studio voices with emotion tags.'
              }
            />
          </div>
        </div>
        {ttsKeyError && (
          <Hint tone="danger">
            ElevenLabs rejected the key saved in this browser ({ttsKeyError}), so {premiumLocked ? 'premium voices stay locked' : 'premium voices are paid from your credits'}. Replace it in{' '}
            <AccountLink tab="keys">Account</AccountLink>.
          </Hint>
        )}
        {!premiumAvailable && (
          <Hint>
            Premium voices are not available on this server right now{billing.elevenlabs_error ? ` (${billing.elevenlabs_error})` : ''}. Add your own ElevenLabs key in{' '}
            <AccountLink tab="keys">Account</AccountLink> to use them.
          </Hint>
        )}
        {premiumAvailable && premiumLocked && (
          <Hint>
            <Lock className="mr-1 inline size-3 align-[-1px]" />
            Premium ElevenLabs voices are paid from your balance: <AccountLink>top up credits</AccountLink> to unlock them, or add your own ElevenLabs key there.
          </Hint>
        )}
        {provider === 'elevenlabs' && hasTtsKey && <Hint tone="accent">Voices are billed to your ElevenLabs account, not to credits.</Hint>}
        {noNativeVoices && (
          <Hint>
            No native {voiceLanguage.name} voices for this ElevenLabs key (Voice Library voices need a paid ElevenLabs plan) — the voices below speak{' '}
            {voiceLanguage.name} with an accent.
          </Hint>
        )}
        {catalogue.loading && (
          <Hint className="flex items-center gap-2">
            <Spinner className="size-3.5" /> Loading {provider === 'elevenlabs' ? 'premium' : 'Edge'} voices…
          </Hint>
        )}
        {catalogue.error && (
          <Hint>
            Could not load the voice list ({catalogue.error}) — every speaker gets a distinct voice automatically.{' '}
            <button type="button" onClick={catalogue.reload} className="font-semibold text-accent hover:text-accent-hover cursor-pointer">
              Retry
            </button>
          </Hint>
        )}
      </div>

      <div className="grid gap-2.5">
        <SectionHead title="Debaters" count={`${debaters} / ${MAX_DEBATERS}`} hint={debaters === 2 ? 'Two debaters argue Pro and Con.' : `${debaters} debaters take turns each round.`} />
        <div className={`hidden gap-3 px-[15px] font-mono text-[10px] tracking-[0.1em] text-dim min-[1100px]:grid ${ROW_COLUMNS}`} aria-hidden="true">
          <span>MODEL</span>
          <span>VOICE</span>
          <span>PERSONA</span>
          <span />
        </div>
        {state.speakers.filter((s) => s.role === 'debater').map(row)}
        {slotsLeft > 0 && (
          <button
            type="button"
            onClick={addSpeaker}
            className="flex h-[60px] items-center justify-center gap-2.5 rounded-card border border-dashed border-white/14 text-sm font-semibold text-text-3 transition-colors hover:border-accent hover:bg-accent/3 hover:text-text cursor-pointer"
          >
            <Plus className="size-4" /> Add debater
            <span className="font-mono text-[11px] font-normal text-dim">
              {slotsLeft} {slotsLeft === 1 ? 'slot' : 'slots'} left
            </span>
          </button>
        )}
      </div>

      <div className="grid gap-2.5">
        <SectionHead title="Host" hint="Moderates the debate and announces the verdict at the end." />
        {state.speakers.filter((s) => s.role === 'moderator').map(row)}
      </div>
    </div>
  );
};
