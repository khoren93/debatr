import { ArrowUpRight, Plus, RefreshCw } from 'lucide-react';
import type { BillingConfig, ModelInfo, TTSProviderName } from '../../api/types';
import { useLeaderboard } from '../../hooks/useLeaderboard';
import type { VoiceCatalogue } from '../../hooks/useVoices';
import { Card, ErrorBox, Hint, Label, Spinner } from '../ui';
import { OptionCard } from './OptionCard';
import { SpeakerCard } from './SpeakerCard';
import {
  MAX_DEBATERS,
  MIN_DEBATERS,
  countDebaters,
  defaultDebater,
  randomizeSpeaker,
  reindexVoices,
  speakerColorOf,
  speakerId,
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
  /** User's own ElevenLabs key (lib/localKeys) — premium voices without credits. */
  hasTtsKey: boolean;
  paidLocked: boolean;
  showErrors: boolean;
}

/** Account page in a new tab: the wizard keeps its state and picks up new keys immediately. */
const AccountLink = ({ children }: { children: string }) => (
  <a href="/account" target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-accent hover:text-accent-hover">
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
  paidLocked,
  showErrors,
}: StepSpeakersProps) => {
  const debaters = countDebaters(state.speakers);
  const premiumAvailable = billing.elevenlabs_available || hasTtsKey;
  // Without a catalogue the server assigns the voices, so there is nothing to pick.
  const voicesAuto = Boolean(catalogue.error);
  // Voice ids are provider-specific: switching the engine drops the explicit choices.
  const setProvider = (next: TTSProviderName) => {
    if (next !== state.provider) patch({ provider: next, voices: {} });
  };
  const takenBy = (index: number) =>
    Object.fromEntries(
      state.speakers.flatMap((s, i) => {
        const voice = resolvedVoices[speakerId(i)];
        return i !== index && voice ? [[voice, s.name.trim() || speakerTagOf(state.speakers, i)]] : [];
      }),
    );
  const { data: leaderboard } = useLeaderboard();
  const rankingFor = (modelId: string) => {
    const entries = leaderboard?.entries ?? [];
    const index = entries.findIndex((e) => e.model_id === modelId);
    return index < 0 ? null : { entry: entries[index], rank: index + 1 };
  };
  const ranks = Object.fromEntries((leaderboard?.entries ?? []).map((e, i) => [e.model_id, i + 1]));

  const updateSpeaker = (index: number, changes: Partial<Speaker>) =>
    patch({ speakers: state.speakers.map((s, i) => (i === index ? { ...s, ...changes } : s)) });

  const setVoice = (index: number, voiceId: string) => patch({ voices: { ...state.voices, [speakerId(index)]: voiceId } });

  const randomizeOne = (index: number) => {
    const others = state.speakers.filter((_, i) => i !== index);
    const { speaker, voiceId } = randomizeSpeaker(state.speakers[index], {
      takenNames: others.map((s) => s.name),
      takenVoices: others.map((_, i) => resolvedVoices[speakerId(i < index ? i : i + 1)]).filter(Boolean),
      models,
      voices: catalogue.voices,
    });
    patch({
      speakers: state.speakers.map((s, i) => (i === index ? speaker : s)),
      voices: voiceId ? { ...state.voices, [speakerId(index)]: voiceId } : state.voices,
    });
  };

  const randomizeAll = () => {
    const speakers: Speaker[] = [];
    const voices = { ...state.voices };
    const takenVoices: string[] = [];
    state.speakers.forEach((original, index) => {
      const { speaker, voiceId } = randomizeSpeaker(original, {
        takenNames: speakers.map((s) => s.name),
        takenVoices,
        models,
        voices: catalogue.voices,
      });
      speakers.push(speaker);
      if (voiceId) {
        voices[speakerId(index)] = voiceId;
        takenVoices.push(voiceId);
      }
    });
    patch({ speakers, voices });
  };

  const addSpeaker = () => {
    if (debaters >= MAX_DEBATERS) return;
    patch({ speakers: [...state.speakers, defaultDebater(debaters)] });
  };

  const removeSpeaker = (index: number) => {
    if (state.speakers[index].role !== 'debater' || debaters <= MIN_DEBATERS) return;
    patch({ speakers: state.speakers.filter((_, i) => i !== index), voices: reindexVoices(state.voices, index) });
  };

  return (
    <div className="mt-[30px] animate-rise">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="text-sm text-muted">Cast the speakers. Each gets a model, a voice and a persona.</div>
        <button
          type="button"
          onClick={randomizeAll}
          disabled={modelsLoading || catalogue.loading}
          className="inline-flex items-center gap-1.5 text-[13px] text-accent hover:text-accent-hover cursor-pointer disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw className="size-3.5" /> Randomize everything
        </button>
      </div>

      {modelsError && <ErrorBox className="mt-4">Could not load the model list: {modelsError}</ErrorBox>}
      {paidLocked && (
        <Hint className="mt-3">
          Paid models are locked: add credits or your own OpenRouter key in <AccountLink>Account</AccountLink>. Free models work right away.
        </Hint>
      )}

      <Card padding="md" className="mt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <Label>Voice engine</Label>
          <span className="text-xs text-muted">
            Own ElevenLabs key? Add it in <AccountLink>Account</AccountLink>
          </span>
        </div>
        <div className="mt-2.5 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr))]">
          <OptionCard
            active={provider === 'edge'}
            onClick={() => setProvider('edge')}
            title="Edge neural"
            right={<span className="font-mono text-[11px] text-accent">FREE</span>}
            text="Good quality, word timestamps, instant."
          />
          <OptionCard
            active={provider === 'elevenlabs'}
            onClick={() => setProvider('elevenlabs')}
            disabled={!premiumAvailable}
            title_={premiumAvailable ? undefined : 'Premium voices are not configured on this server — add your own ElevenLabs key in Account'}
            title="Premium neural"
            right={<span className="font-mono text-[11px] text-accent">{hasTtsKey ? 'YOUR KEY' : `$${billing.tts_price_per_min.toFixed(2)} / min`}</span>}
            text="ElevenLabs studio voices with emotion tags."
          />
        </div>
        {!premiumAvailable && (
          <Hint>
            Premium voices are not available on this server right now{billing.elevenlabs_error ? ` (${billing.elevenlabs_error})` : ''}. Add your own ElevenLabs key in{' '}
            <AccountLink>Account</AccountLink> to use them.
          </Hint>
        )}
        {provider === 'elevenlabs' && hasTtsKey && <Hint tone="accent">Voices are billed to your ElevenLabs account, not to credits.</Hint>}
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
      </Card>

      <div className="mt-4 grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))]">
        {state.speakers.map((speaker, index) => (
          <SpeakerCard
            key={speaker.key}
            speaker={speaker}
            color={speakerColorOf(state.speakers, index)}
            tag={speakerTagOf(state.speakers, index)}
            modelId={speaker.model_id || defaultModelId}
            voiceId={resolvedVoices[speakerId(index)] ?? ''}
            models={models}
            modelsLoading={modelsLoading}
            paidLocked={paidLocked}
            ranking={speaker.role === 'debater' && leaderboard ? rankingFor(speaker.model_id || defaultModelId) : undefined}
            ranks={ranks}
            voices={catalogue.voices}
            voicesLoading={catalogue.loading}
            voicesAuto={voicesAuto}
            voicesTakenBy={takenBy(index)}
            showVoiceLanguages={provider === 'elevenlabs'}
            removable={speaker.role === 'debater' && debaters > MIN_DEBATERS}
            showErrors={showErrors}
            onChange={(changes) => updateSpeaker(index, changes)}
            onVoice={(voiceId) => setVoice(index, voiceId)}
            onRandomize={() => randomizeOne(index)}
            onRemove={() => removeSpeaker(index)}
          />
        ))}
        {debaters < MAX_DEBATERS && (
          <button
            type="button"
            onClick={addSpeaker}
            className="flex min-h-[240px] flex-col items-center justify-center gap-2 rounded-panel border border-dashed border-line-2 text-muted transition-colors hover:border-accent hover:text-text cursor-pointer"
          >
            <span className="grid size-10 place-items-center rounded-xl bg-surface-2">
              <Plus className="size-5" />
            </span>
            <span className="text-sm font-semibold">Add speaker</span>
            <span className="text-xs text-dim">Up to {MAX_DEBATERS} debaters</span>
          </button>
        )}
      </div>
    </div>
  );
};
