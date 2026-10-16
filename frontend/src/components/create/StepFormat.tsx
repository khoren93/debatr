import { KeyRound } from 'lucide-react';
import type { TtsKeyCheck, TtsKeyStatus } from '../../hooks/useElevenLabsKeyStatus';
import { Card, Chip, Hint, Label, LinkButton } from '../ui';
import { OptionCard } from './OptionCard';
import { OUTPUT_OPTIONS, QUALITY_OPTIONS, type WizardState } from './wizardState';

interface StepFormatProps {
  state: WizardState;
  patch: (patch: Partial<WizardState>) => void;
  /** Masked key already stored on the account, if any. */
  accountKeyMasked: string | null;
  /** Browser-only keys (lib/localKeys), managed on the Account page. */
  openrouterKey: string;
  /** The browser's ElevenLabs key, as checked against ElevenLabs. */
  ttsKeyCheck: TtsKeyCheck;
}

const KeyStatus = ({ label, value, bad = false, title }: { label: string; value: string | null; bad?: boolean; title?: string }) => (
  <span title={title} className="inline-flex items-center gap-1.5 rounded-full border border-line-2 bg-ink px-2.5 py-1 text-[11px]">
    <span className={`size-1.5 rounded-full ${bad ? 'bg-con' : value ? 'bg-ok' : 'bg-line-3'}`} aria-hidden="true" />
    <span className="font-semibold text-text-3">{label}</span>
    <span className="text-muted">{value ?? 'not set'}</span>
  </span>
);

const TTS_KEY_LABELS: Record<TtsKeyStatus, string | null> = {
  none: null,
  checking: 'checking…',
  valid: 'set in this browser',
  invalid: 'rejected by ElevenLabs',
  unknown: 'set in this browser',
};

export const StepFormat = ({ state, patch, accountKeyMasked, openrouterKey, ttsKeyCheck }: StepFormatProps) => {
  const toggleOutput = (value: WizardState['outputs'][number]) =>
    patch({
      outputs: state.outputs.includes(value)
        ? state.outputs.filter((o) => o !== value)
        : OUTPUT_OPTIONS.map((o) => o.value).filter((o) => o === value || state.outputs.includes(o)),
    });

  return (
    <div className="mt-[30px] grid gap-3.5 animate-rise">
      <Card padding="md">
        <Label>Writing style</Label>
        <div className="mt-2.5 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]">
          <OptionCard
            active={state.output_style === 'spoken'}
            onClick={() => patch({ output_style: 'spoken' })}
            title="Spoken"
            text="Short quotable sentences, no lists or headers. Voices much better."
          />
          <OptionCard
            active={state.output_style === 'markdown'}
            onClick={() => patch({ output_style: 'markdown' })}
            title="Written"
            text="Structured prose with headings. Best for reading and Markdown export."
          />
        </div>
      </Card>

      <Card padding="md">
        <Label>Outputs</Label>
        <div className="mt-2.5 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr))]">
          {OUTPUT_OPTIONS.map((o) => (
            <OptionCard
              key={o.value}
              active={state.outputs.includes(o.value)}
              onClick={() => toggleOutput(o.value)}
              checkbox
              leading={<span className="shrink-0 rounded-[4px]" style={{ width: o.icon.w, height: o.icon.h, background: o.icon.color }} aria-hidden="true" />}
              title={o.label}
              text={o.text}
            />
          ))}
        </div>
        {state.outputs.length === 0 && <Hint>No outputs selected — the debate runs as text only; you can build audio and video later.</Hint>}
        <div className="mt-3.5 flex flex-wrap items-center gap-2.5 text-[13px] text-muted">
          Quality
          {QUALITY_OPTIONS.map((q) => (
            <Chip key={q.value} size="sm" active={state.quality === q.value} onClick={() => patch({ quality: q.value })}>
              {q.label}
            </Chip>
          ))}
        </div>
      </Card>

      <Card padding="md">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 basis-[260px]">
            <Label>Your own API keys</Label>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              Optional. An OpenRouter key unlocks paid models without credits; an ElevenLabs key makes premium voices free of credits. Keys are managed in Account and stay in this browser.
            </p>
          </div>
          <LinkButton to="/account" variant="secondary" size="sm" newTab icon={<KeyRound className="size-3.5" />}>
            Manage keys
          </LinkButton>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <KeyStatus label="OpenRouter" value={openrouterKey ? 'set in this browser' : accountKeyMasked ? `account key ${accountKeyMasked}` : null} />
          <KeyStatus
            label="ElevenLabs"
            value={TTS_KEY_LABELS[ttsKeyCheck.status]}
            bad={ttsKeyCheck.status === 'invalid'}
            title={ttsKeyCheck.error ?? undefined}
          />
        </div>
      </Card>
    </div>
  );
};
