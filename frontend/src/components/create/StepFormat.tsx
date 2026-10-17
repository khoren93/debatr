import { KeyRound, PenTool, SearchCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import type { ImageSource } from '../../api/types';
import type { TtsKeyCheck, TtsKeyStatus } from '../../hooks/useElevenLabsKeyStatus';
import { accountPath } from '../account/tabs';
import { Card, Chip, Hint, Label, LinkButton, Segmented } from '../ui';
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
  /** No balance: AI pictures (system key) are locked. */
  aiImagesLocked: boolean;
  /** No balance and no own OpenRouter key: the paid fact-check is locked. */
  factCheckLocked: boolean;
}

/** A setting row with an on/off switch (same look as the auto-publish switch). */
const SwitchRow = ({ icon, title, text, on, disabled = false, onToggle, children }: { icon: ReactNode; title: string; text: string; on: boolean; disabled?: boolean; onToggle: () => void; children?: ReactNode }) => (
  <div className={`mt-3.5 rounded-field border border-line-2 bg-ink transition-colors ${disabled ? 'opacity-60' : 'hover:border-line-3'}`}>
    <button type="button" role="switch" aria-checked={on} disabled={disabled} onClick={onToggle} className="flex w-full items-start gap-3 p-3.5 text-left disabled:cursor-not-allowed cursor-pointer">
      <span className={`mt-0.5 shrink-0 ${on ? 'text-accent' : 'text-muted'}`}>{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">{title}</span>
        <span className="mt-0.5 block text-xs leading-relaxed text-muted">{text}</span>
      </span>
      <span className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${on ? 'bg-accent' : 'bg-line-3'}`} aria-hidden="true">
        <span className={`absolute top-0.5 size-4 rounded-full bg-ink transition-[left] ${on ? 'left-[18px]' : 'left-0.5'}`} />
      </span>
    </button>
    {children && <div className="border-t border-line px-3.5 pb-3.5 pt-3">{children}</div>}
  </div>
);

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

export const StepFormat = ({ state, patch, accountKeyMasked, openrouterKey, ttsKeyCheck, aiImagesLocked, factCheckLocked }: StepFormatProps) => {
  const toggleOutput = (value: WizardState['outputs'][number]) =>
    patch({
      outputs: state.outputs.includes(value)
        ? state.outputs.filter((o) => o !== value)
        : OUTPUT_OPTIONS.map((o) => o.value).filter((o) => o === value || state.outputs.includes(o)),
    });

  const withAudio = state.outputs.includes('audio');
  const visualsOn = state.visuals;
  const images: ImageSource = withAudio && !(state.images === 'ai' && aiImagesLocked) ? state.images : 'off';
  const factCheckOn = visualsOn && state.fact_check && !factCheckLocked;

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
        <SwitchRow
          icon={<PenTool className="size-4" />}
          title="Visual scenes"
          text="Charts, numbers and hand-drawn sketches appear next to every turn as the debate runs, and in the video exactly when they are said. Debaters can ask for visuals and challenge each other's figures."
          on={visualsOn}
          onToggle={() => patch({ visuals: !state.visuals })}
        >
          {visualsOn && (
            <div className="flex flex-wrap items-center gap-2.5 text-[13px] text-muted">
              Pictures
              <Segmented
                size="sm"
                value={images}
                onChange={(value) => patch({ images: value })}
                options={[
                  { value: 'off', label: 'None' },
                  { value: 'stock', label: 'Free photos', disabled: !withAudio },
                  { value: 'ai', label: 'AI images', disabled: !withAudio || aiImagesLocked },
                ]}
              />
              <span className="basis-full text-xs leading-relaxed">
                {!withAudio
                  ? 'Pictures are found while the audio is built — select Audio to add them.'
                  : images === 'ai'
                    ? 'Generated for the scenes that show a real place or thing, about $0.01 each from your balance; checked before use.'
                    : images === 'stock'
                      ? 'Freely licensed photos from Wikimedia Commons, with the author and licence in the frame.'
                      : aiImagesLocked
                        ? 'AI images are paid from your balance — top up to use them.'
                        : 'Only charts and drawings.'}
              </span>
            </div>
          )}
        </SwitchRow>
        <SwitchRow
          icon={<SearchCheck className="size-4" />}
          title="Fact-check figures"
          text={
            !visualsOn
              ? 'Checks the figures and quotes of the visual scenes — turn the scenes on first.'
              : factCheckLocked
                ? 'A web search checks the figures on screen; it is paid from your balance or your OpenRouter key.'
                : 'A web search checks the figures and quotes shown on screen (about $0.006 each). Opponents and the judge see the results.'
          }
          on={factCheckOn}
          disabled={!visualsOn || factCheckLocked}
          onToggle={() => patch({ fact_check: !state.fact_check })}
        />
      </Card>

      <Card padding="md">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 basis-[260px]">
            <Label>Your own API keys</Label>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              Optional. An OpenRouter key unlocks paid models without credits; an ElevenLabs key makes premium voices free of credits. Keys are managed in Account and stay in this browser.
            </p>
          </div>
          <LinkButton to={accountPath('keys')} variant="secondary" size="sm" newTab icon={<KeyRound className="size-3.5" />}>
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
