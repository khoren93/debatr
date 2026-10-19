import { PenLine, Trash2 } from 'lucide-react';
import type { ReactNode } from 'react';
import type { ModelInfo, VoiceInfo } from '../../api/types';
import { applyStyle, clearStyle, detectStyle } from '../../data/styles';
import { Dropdown, Hint } from '../ui';
import { ModelPicker } from './ModelPicker';
import { PersonaPicker } from './PersonaPicker';
import { useVoicePreview } from './useVoicePreview';
import { VoicePicker } from './VoicePicker';
import { VoicePreviewButton } from './VoicePreviewButton';
import { SIDE_OPTIONS, type Speaker } from './wizardState';

/** Columns of the wide layout; the header row above the debaters uses the same template. */
export const ROW_COLUMNS = 'min-[1100px]:grid-cols-[minmax(0,1.3fr)_118px_minmax(0,1fr)_minmax(0,1.15fr)_126px]';

interface SpeakerRowProps {
  speaker: Speaker;
  /** On-stage name, derived from the model (lib/modelNames). */
  name: string;
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
  /** System prompt editor open. */
  expanded: boolean;
  removable: boolean;
  showErrors: boolean;
  onChange: (patch: Partial<Speaker>) => void;
  onVoice: (voiceId: string) => void;
  onToggleExpanded: () => void;
  onRemove: () => void;
}

const RowAction = ({ title, onClick, active, color, children }: { title: string; onClick: () => void; active?: boolean; color?: string; children: ReactNode }) => (
  <button
    type="button"
    onClick={onClick}
    title={title}
    aria-label={title}
    aria-pressed={active}
    className="grid size-[38px] shrink-0 place-items-center rounded-[11px] border border-white/8 bg-ink text-text-3 transition-colors hover:bg-surface-2 cursor-pointer"
    style={active ? { color } : undefined}
  >
    {children}
  </button>
);

/** One speaker of step 2: model, voice and persona fields plus preview / prompt / remove. */
export const SpeakerRow = ({
  speaker,
  name,
  color,
  tag,
  modelId,
  voiceId,
  models,
  modelsLoading,
  paidLocked,
  ranks,
  voices,
  voicesLoading,
  voicesAuto,
  voicesTakenBy,
  showVoiceLanguages,
  voiceLanguage,
  expanded,
  removable,
  showErrors,
  onChange,
  onVoice,
  onToggleExpanded,
  onRemove,
}: SpeakerRowProps) => {
  const style = detectStyle(speaker.prompt);
  const preview = useVoicePreview();
  const sample = voicesAuto ? null : (voices.find((v) => v.id === voiceId)?.preview_url ?? null);

  return (
    // An open picker lifts its row above the rows below it.
    <div className={`relative grid items-center gap-3 rounded-card border border-line bg-surface px-3.5 py-3 has-[[aria-expanded=true]]:z-30 ${ROW_COLUMNS}`}>
      <div className="min-w-0">
        <ModelPicker
          value={modelId}
          models={models}
          loading={modelsLoading}
          paidLocked={paidLocked}
          ranks={ranks}
          color={color}
          tag={tag}
          speakerName={name}
          onChange={(id) => onChange({ model_id: id })}
        />
        {showErrors && !modelId && !modelsLoading && <Hint tone="danger">Pick a model for this speaker.</Hint>}
      </div>
      {speaker.role === 'debater' ? (
        <Dropdown
          aria-label={`Side of ${name}`}
          value={speaker.side ?? ''}
          placeholder="In prompt"
          onChange={(side) => side && onChange({ side })}
          menuWidth={200}
          options={SIDE_OPTIONS.map((o) => ({ value: o.value, label: o.label, hint: o.hint }))}
        />
      ) : (
        // The host takes no side: an empty cell keeps the columns aligned.
        <span className="hidden text-center font-mono text-[11px] text-dim min-[1100px]:block">neutral</span>
      )}
      <VoicePicker
        value={voiceId}
        voices={voices}
        loading={voicesLoading}
        auto={voicesAuto}
        takenBy={voicesTakenBy}
        showLanguages={showVoiceLanguages}
        language={voiceLanguage}
        color={color}
        onChange={onVoice}
      />
      {/* Narrow rows: the actions sit next to the persona instead of on a line of their own. */}
      <div className="flex items-center gap-1.5 min-[1100px]:contents">
        <div className="min-w-0 flex-1">
          <PersonaPicker
            value={style}
            color={color}
            onChange={(s) => onChange({ prompt: applyStyle(speaker.prompt, s) })}
            onCustom={() => {
              onChange({ prompt: clearStyle(speaker.prompt) });
              if (!expanded) onToggleExpanded();
            }}
          />
        </div>
        <div className="flex items-center gap-1.5 min-[1100px]:justify-end">
          {/* Edge voices have no samples: no button rather than a dead one. */}
          {sample && <VoicePreviewButton url={sample} playing={preview.playing === sample} onToggle={() => preview.toggle(sample)} color={color} />}
          <RowAction title="Edit system prompt" onClick={onToggleExpanded} active={expanded} color={color}>
            <PenLine className="size-4" />
          </RowAction>
          {removable && (
            <RowAction title="Remove" onClick={onRemove}>
              <Trash2 className="size-4" />
            </RowAction>
          )}
        </div>
      </div>
      {expanded && (
        <div className="col-span-full grid gap-1.5 pt-1">
          <div className="flex justify-between gap-3 text-xs text-muted">
            <span>System prompt</span>
            <span className="font-mono text-[11px] text-dim">{style?.full ?? 'Custom'}</span>
          </div>
          <textarea
            rows={3}
            value={speaker.prompt}
            onChange={(e) => onChange({ prompt: e.target.value })}
            maxLength={4000}
            aria-label={`System prompt of ${name}`}
            className="w-full resize-y rounded-field border border-line-2 bg-ink px-3.5 py-3 text-[13px] leading-[1.55] text-text-2 outline-none transition-colors focus:border-accent"
          />
        </div>
      )}
    </div>
  );
};
