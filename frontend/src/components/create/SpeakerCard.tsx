import { ArrowUpRight, RefreshCw, Trophy, X } from 'lucide-react';
import type { LeaderboardEntry, ModelInfo, VoiceInfo } from '../../api/types';
import { applyStyle, detectStyle } from '../../data/styles';
import { Hint } from '../ui';
import { ModelPicker } from './ModelPicker';
import { PersonaPicker } from './PersonaPicker';
import { VoicePicker } from './VoicePicker';
import type { Speaker } from './wizardState';

interface SpeakerCardProps {
  speaker: Speaker;
  color: string;
  tag: string;
  /** Effective model id (explicit choice or the default free model). */
  modelId: string;
  /** Effective voice id (explicit choice or the provider default). */
  voiceId: string;
  models: ModelInfo[];
  modelsLoading: boolean;
  /** Paid models cannot be used: no own key and no credits. */
  paidLocked: boolean;
  /** Audience ranking of the chosen model: null = not ranked yet, undefined = not shown. */
  ranking?: { entry: LeaderboardEntry; rank: number } | null;
  /** Audience rank per model id for the model list. */
  ranks: Record<string, number>;
  voices: VoiceInfo[];
  voicesLoading: boolean;
  /** Premium list unavailable: voices are assigned by the server. */
  voicesAuto: boolean;
  /** Speaker name per voice id used by another speaker. */
  voicesTakenBy: Record<string, string>;
  showVoiceLanguages: boolean;
  /** Debate language for the voice list: ISO code + display name. */
  voiceLanguage: { code: string; name: string };
  removable: boolean;
  showErrors: boolean;
  onChange: (patch: Partial<Speaker>) => void;
  onVoice: (voiceId: string) => void;
  onRandomize: () => void;
  onRemove: () => void;
}

export const SpeakerCard = ({
  speaker,
  color,
  tag,
  modelId,
  voiceId,
  models,
  modelsLoading,
  paidLocked,
  ranking,
  ranks,
  voices,
  voicesLoading,
  voicesAuto,
  voicesTakenBy,
  showVoiceLanguages,
  voiceLanguage,
  removable,
  showErrors,
  onChange,
  onVoice,
  onRandomize,
  onRemove,
}: SpeakerCardProps) => {
  const activeStyle = detectStyle(speaker.prompt);
  const nameMissing = showErrors && !speaker.name.trim();
  const modelMissing = showErrors && !modelId && !modelsLoading;

  return (
    <div className="rounded-panel border border-line bg-surface p-5" style={{ borderTop: `3px solid ${color}` }}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] tracking-[0.1em]" style={{ color }}>
          {tag}
        </span>
        <div className="-mr-1.5 flex items-center gap-0.5">
          {removable && (
            <button
              type="button"
              onClick={onRemove}
              className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-con cursor-pointer"
              aria-label="Remove speaker"
              title="Remove speaker"
            >
              <X className="size-3.5" />
            </button>
          )}
          <button
            type="button"
            onClick={onRandomize}
            className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text cursor-pointer"
            aria-label="Randomize this speaker"
            title="Randomize this speaker"
          >
            <RefreshCw className="size-3.5" />
          </button>
        </div>
      </div>

      <input
        value={speaker.name}
        onChange={(e) => onChange({ name: e.target.value })}
        placeholder="Speaker name"
        maxLength={100}
        aria-label="Speaker name"
        className="mt-3 w-full bg-transparent p-0 font-display text-2xl font-bold tracking-[-0.02em] text-text outline-none placeholder:text-dim"
      />
      {nameMissing && <Hint tone="danger">Every speaker needs a name.</Hint>}

      <div className="mt-3.5 text-xs text-muted">Model</div>
      <div className="mt-1.5 flex items-center gap-2">
        <ModelPicker value={modelId} models={models} loading={modelsLoading} paidLocked={paidLocked} ranks={ranks} onChange={(id) => onChange({ model_id: id })} />
      </div>
      {modelMissing && <Hint tone="danger">Pick a model for this speaker.</Hint>}
      {ranking && (
        <div className="mt-1.5 flex items-center justify-between gap-2 text-[11px] text-muted">
          <span className="inline-flex min-w-0 items-center gap-1 truncate" title="Audience ranking of this model">
            <Trophy className="size-3 shrink-0" /> #{ranking.rank} · rating {ranking.entry.rating} · {ranking.entry.votes} votes
          </span>
          {/* New tab: the wizard keeps its state, but leaving it mid-setup would be annoying. */}
          <a href={`/gallery?model=${encodeURIComponent(ranking.entry.model_id)}`} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-0.5 text-accent hover:text-accent-hover">
            {ranking.entry.debates} {ranking.entry.debates === 1 ? 'debate' : 'debates'} <ArrowUpRight className="size-3" />
          </a>
        </div>
      )}

      <div className="mt-3 text-xs text-muted">Voice</div>
      <div className="mt-1.5 flex">
        <VoicePicker
          value={voiceId}
          voices={voices}
          loading={voicesLoading}
          auto={voicesAuto}
          takenBy={voicesTakenBy}
          showLanguages={showVoiceLanguages}
          language={voiceLanguage}
          onChange={onVoice}
        />
      </div>

      <div className="mt-3 text-xs text-muted">Persona</div>
      <div className="mt-1.5 flex">
        <PersonaPicker value={activeStyle} color={color} onChange={(s) => onChange({ prompt: applyStyle(speaker.prompt, s) })} />
      </div>

      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-muted hover:text-text">Edit system prompt ›</summary>
        <textarea
          rows={4}
          value={speaker.prompt}
          onChange={(e) => onChange({ prompt: e.target.value })}
          maxLength={4000}
          aria-label="System prompt"
          className="mt-2 w-full resize-y rounded-[10px] border border-line-2 bg-ink px-3 py-2.5 text-xs leading-relaxed text-text-3 outline-none transition-colors focus:border-accent"
        />
      </details>
    </div>
  );
};
