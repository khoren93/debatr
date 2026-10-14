import { Link } from 'react-router-dom';
import type { BillingConfig } from '../../api/types';
import { setLocalKey } from '../../lib/localKeys';
import { Card, Chip, Hint, Input, Label } from '../ui';
import { OptionCard } from './OptionCard';
import { OUTPUT_OPTIONS, QUALITY_OPTIONS, type WizardState } from './wizardState';

interface StepFormatProps {
  state: WizardState;
  patch: (patch: Partial<WizardState>) => void;
  billing: BillingConfig;
  /** Masked key already stored on the account, if any. */
  accountKeyMasked: string | null;
  /** Browser-only keys (lib/localKeys); editing them here updates the Account page too. */
  openrouterKey: string;
  elevenlabsKey: string;
}

export const StepFormat = ({ state, patch, billing, accountKeyMasked, openrouterKey, elevenlabsKey }: StepFormatProps) => {
  const toggleOutput = (value: WizardState['outputs'][number]) =>
    patch({
      outputs: state.outputs.includes(value)
        ? state.outputs.filter((o) => o !== value)
        : OUTPUT_OPTIONS.map((o) => o.value).filter((o) => o === value || state.outputs.includes(o)),
    });
  const premiumPrice = `$${billing.tts_price_per_min.toFixed(2)} / min`;
  const hasKey = openrouterKey.length > 0;
  const hasTtsKey = elevenlabsKey.length > 0;
  const premiumAvailable = billing.elevenlabs_available || hasTtsKey;

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
        <Label>Voice engine</Label>
        <div className="mt-2.5 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]">
          <OptionCard
            active={state.provider === 'edge'}
            onClick={() => patch({ provider: 'edge' })}
            title="Edge neural"
            right={<span className="font-mono text-[11px] text-accent">FREE</span>}
            text="Good quality, word timestamps, instant."
          />
          <OptionCard
            active={state.provider === 'elevenlabs'}
            onClick={() => patch({ provider: 'elevenlabs' })}
            disabled={!premiumAvailable}
            title_={premiumAvailable ? undefined : 'Premium voices are not configured on this server — add your own ElevenLabs key below'}
            title="Premium neural"
            right={<span className="font-mono text-[11px] text-accent">{hasTtsKey ? 'YOUR KEY' : premiumPrice}</span>}
            text="Studio-grade voices with emotion tags."
          />
        </div>
        {!premiumAvailable && (
          <Hint>
            Premium voices are not available on this server right now{billing.elevenlabs_error ? ` (${billing.elevenlabs_error})` : ''} — the free Edge voices are used. Add your own ElevenLabs key below to use them anyway.
          </Hint>
        )}
        {state.provider === 'elevenlabs' && hasTtsKey && <Hint tone="accent">Voices are billed to your ElevenLabs account, not to credits.</Hint>}
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

      <details className="rounded-panel border border-line bg-surface px-5 py-4.5">
        <summary className="flex cursor-pointer items-center justify-between gap-3 text-[13px] font-semibold text-text-3">
          Use your own OpenRouter key
          <span className={`font-normal ${hasKey ? 'text-accent' : 'text-muted'}`}>{hasKey ? 'key set ›' : 'optional ›'}</span>
        </summary>
        <Input
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder="sk-or-…"
          value={openrouterKey}
          onChange={(e) => setLocalKey('openrouter', e.target.value)}
          maxLength={300}
          aria-label="OpenRouter API key"
          className="mt-3 font-mono"
        />
        <Hint>Bypasses credit limits and unlocks paid models. Stored only in this browser.</Hint>
        {accountKeyMasked && !hasKey && <Hint tone="accent">Your account already has a key ({accountKeyMasked}) — it is used automatically.</Hint>}
      </details>

      <details className="rounded-panel border border-line bg-surface px-5 py-4.5">
        <summary className="flex cursor-pointer items-center justify-between gap-3 text-[13px] font-semibold text-text-3">
          Use your own ElevenLabs key
          <span className={`font-normal ${hasTtsKey ? 'text-accent' : 'text-muted'}`}>{hasTtsKey ? 'key set ›' : 'optional ›'}</span>
        </summary>
        <Input
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder="sk_…"
          value={elevenlabsKey}
          onChange={(e) => setLocalKey('elevenlabs', e.target.value)}
          maxLength={200}
          aria-label="ElevenLabs API key"
          className="mt-3 font-mono"
        />
        <Hint>
          Premium voices on your own ElevenLabs account, including your cloned voices. Stored only in this browser — manage it in{' '}
          <Link to="/account" className="text-accent hover:text-accent-hover">
            Account
          </Link>
          .
        </Hint>
      </details>
    </div>
  );
};
