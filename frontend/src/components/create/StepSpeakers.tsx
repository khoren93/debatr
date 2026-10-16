import { Plus, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { ModelInfo } from '../../api/types';
import { useLeaderboard } from '../../hooks/useLeaderboard';
import type { VoiceCatalogue } from '../../hooks/useVoices';
import { ErrorBox, Hint, Spinner } from '../ui';
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
  paidLocked: boolean;
  showErrors: boolean;
}

export const StepSpeakers = ({ state, patch, models, modelsLoading, modelsError, defaultModelId, catalogue, resolvedVoices, paidLocked, showErrors }: StepSpeakersProps) => {
  const debaters = countDebaters(state.speakers);
  const { data: leaderboard } = useLeaderboard();
  const rankingFor = (modelId: string) => {
    const entries = leaderboard?.entries ?? [];
    const index = entries.findIndex((e) => e.model_id === modelId);
    return index < 0 ? null : { entry: entries[index], rank: index + 1 };
  };

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
      {catalogue.error && (
        <ErrorBox className="mt-4">
          Could not load voices: {catalogue.error}{' '}
          <button type="button" onClick={catalogue.reload} className="font-semibold underline underline-offset-2 hover:text-text cursor-pointer">
            Retry
          </button>
        </ErrorBox>
      )}
      {catalogue.loading && (
        <div className="mt-4 flex items-center gap-2 text-xs text-muted">
          <Spinner className="size-3.5" /> Loading {state.provider === 'elevenlabs' ? 'premium' : 'Edge'} voices…
        </div>
      )}
      {paidLocked && (
        <Hint className="mt-3">
          Paid models are locked: add credits in{' '}
          <Link to="/account" className="text-accent hover:text-accent-hover">
            Account
          </Link>{' '}
          or use your own OpenRouter key (step 3). Free models work right away.
        </Hint>
      )}

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
            voices={catalogue.voices}
            voicesLoading={catalogue.loading}
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
