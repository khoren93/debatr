import { useState, type FormEvent, type ReactNode } from 'react';
import { Lock, Trash2 } from 'lucide-react';
import { removeOpenRouterKey } from '../../api/auth';
import { getErrorMessage } from '../../api/client';
import type { User } from '../../api/types';
import { checkElevenLabsKey } from '../../hooks/useElevenLabsKeyStatus';
import { maskKey, setLocalKey, useLocalKey, type LocalKeyName } from '../../lib/localKeys';
import { Button, ConfirmDialog, Input, useToast } from '../ui';

interface Provider {
  name: LocalKeyName;
  label: string;
  /** Letter tile from the design. */
  logo: string;
  logoBg: string;
  placeholder: string;
  description: string;
  hint: string;
  maxLength: number;
  /** Optional check before saving; resolves to an error message or null. */
  validate?: (key: string) => Promise<string | null>;
}

const validateElevenLabsKey = (key: string) =>
  checkElevenLabsKey(key).then(({ status, error }) =>
    status === 'valid' ? null : status === 'invalid' ? `ElevenLabs rejected the key: ${error}` : `Could not check the key: ${error}`,
  );

const PROVIDERS: Provider[] = [
  {
    name: 'elevenlabs',
    label: 'ElevenLabs',
    logo: 'XI',
    logoBg: '#F2F3F7',
    placeholder: 'sk_…',
    description: 'Premium and cloned voices billed to your ElevenLabs account instead of credits.',
    hint: 'Needs the Text to Speech and Voices read permissions.',
    maxLength: 200,
    validate: validateElevenLabsKey,
  },
  {
    name: 'openrouter',
    label: 'OpenRouter',
    logo: 'OR',
    logoBg: '#9C8CFF',
    placeholder: 'sk-or-…',
    description: 'Runs the models on your OpenRouter account. Takes priority over the key saved on your account.',
    hint: 'Create one at openrouter.ai/keys.',
    maxLength: 300,
  },
];

const StatusPill = ({ connected }: { connected: boolean }) => (
  <span
    className={`inline-flex items-center gap-1.5 rounded-full px-[9px] py-[3px] font-mono text-[10px] tracking-[0.06em] ${
      connected ? 'bg-ok/12 text-ok' : 'bg-surface-2 text-muted'
    }`}
  >
    <span className={`size-[5px] rounded-full ${connected ? 'bg-ok' : 'bg-muted'}`} />
    {connected ? 'CONNECTED' : 'NOT CONNECTED'}
  </span>
);

const ProviderCard = ({ provider, extra }: { provider: Provider; extra?: ReactNode }) => {
  const toast = useToast();
  const stored = useLocalKey(provider.name);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setOpen(false);
    setDraft('');
    setError(null);
  };

  const save = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const key = draft.trim();
    if (!key) {
      setError(`Paste your ${provider.label} key first`);
      return;
    }
    setSaving(true);
    setError(null);
    const problem = provider.validate ? await provider.validate(key) : null;
    setSaving(false);
    if (problem) {
      setError(problem);
      return;
    }
    setLocalKey(provider.name, key);
    toast.success(`${provider.label} key saved in this browser`);
    close();
  };

  const remove = () => {
    setLocalKey(provider.name, '');
    toast.info(`${provider.label} key removed from this browser`);
    close();
  };

  return (
    <div className="rounded-panel border border-line bg-surface p-[clamp(18px,2.6vw,24px)]">
      <div className="flex flex-wrap items-center gap-3.5">
        <div
          className="grid size-11 shrink-0 place-items-center rounded-[13px] font-display text-[17px] font-extrabold text-ink"
          style={{ background: provider.logoBg }}
          aria-hidden="true"
        >
          {provider.logo}
        </div>
        <div className="min-w-[180px] flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="text-base font-bold">{provider.label}</span>
            <StatusPill connected={Boolean(stored)} />
          </div>
          <div className="mt-1 text-[13px] leading-normal text-pretty text-muted">{provider.description}</div>
          {stored && <div className="mt-1 font-mono text-xs text-text-3">{maskKey(stored)} · saved in this browser</div>}
        </div>
        <div className="flex items-center gap-2">
          {stored && !open && (
            <Button variant="danger" size="sm" onClick={remove} aria-label={`Remove ${provider.label} key`} title="Remove key" icon={<Trash2 className="size-3.5" />} />
          )}
          {open ? (
            <Button variant="secondary" size="sm" onClick={close} disabled={saving}>
              Cancel
            </Button>
          ) : (
            <Button variant={stored ? 'secondary' : 'light'} size="sm" onClick={() => setOpen(true)}>
              {stored ? 'Replace' : 'Add key'}
            </Button>
          )}
        </div>
      </div>
      {open && (
        <form onSubmit={save} className="mt-4 border-t border-line pt-4">
          <div className="flex flex-wrap gap-2">
            <Input
              type="password"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={provider.placeholder}
              autoComplete="off"
              spellCheck={false}
              maxLength={provider.maxLength}
              autoFocus
              aria-label={`${provider.label} API key`}
              className="min-w-[200px] flex-1 font-mono text-[13px]!"
            />
            <Button type="submit" loading={saving}>
              Save key
            </Button>
          </div>
          <div className={`mt-2.5 text-xs ${error ? 'text-con' : 'text-dim'}`}>{error ?? provider.hint}</div>
        </form>
      )}
      {extra}
    </div>
  );
};

/** Legacy OpenRouter key saved (encrypted) on the account: shown so it can still be removed. */
const AccountKeyNote = ({ masked, onUser }: { masked: string; onUser: (user: User) => void }) => {
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const [removing, setRemoving] = useState(false);

  const remove = async () => {
    setRemoving(true);
    try {
      onUser(await removeOpenRouterKey());
      toast.success('Account OpenRouter key removed');
      setConfirm(false);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setRemoving(false);
    }
  };

  return (
    <div className="mt-4 border-t border-line pt-3.5 text-xs leading-relaxed text-muted">
      A key <span className="font-mono text-text-3">{masked}</span> is also saved on your account and is used when this browser has none.{' '}
      <button type="button" onClick={() => setConfirm(true)} className="cursor-pointer font-semibold text-con hover:underline">
        Remove it
      </button>
      <ConfirmDialog
        open={confirm}
        title="Remove account OpenRouter key?"
        body="Paid models will be charged to your credits unless this browser has its own key."
        confirmLabel="Remove key"
        danger
        busy={removing}
        onConfirm={remove}
        onClose={() => setConfirm(false)}
      />
    </div>
  );
};

/** Personal provider keys kept in localStorage only (lib/localKeys), one card per provider. */
export const ProviderKeys = ({ user, onUser }: { user: User; onUser: (user: User) => void }) => (
  <div className="grid grid-cols-1 gap-3.5">
    <div className="flex items-start gap-3.5 rounded-[16px] border border-pro/22 bg-pro/7 px-5 py-4">
      <div className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-pro/16 text-pro" aria-hidden="true">
        <Lock className="size-3.5" />
      </div>
      <p className="text-[13px] leading-[1.55] text-pretty text-text-3">
        <strong className="text-text">Keys stay in this browser.</strong> They're never stored in our database: a key travels only with the request that needs
        it and sits in a temporary job queue for at most 24 hours.
      </p>
    </div>
    {PROVIDERS.map((p) => (
      <ProviderCard
        key={p.name}
        provider={p}
        extra={p.name === 'openrouter' && user.openrouter_key_masked ? <AccountKeyNote masked={user.openrouter_key_masked} onUser={onUser} /> : undefined}
      />
    ))}
  </div>
);
