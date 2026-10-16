import { useState, type FormEvent, type ReactNode } from 'react';
import { Trash2, X } from 'lucide-react';
import { removeOpenRouterKey } from '../../api/auth';
import { getErrorMessage } from '../../api/client';
import type { User } from '../../api/types';
import { checkElevenLabsKey } from '../../hooks/useElevenLabsKeyStatus';
import { maskKey, setLocalKey, useLocalKey, type LocalKeyName } from '../../lib/localKeys';
import { Button, Card, ConfirmDialog, Hint, Input, Label, SectionLabel, useToast } from '../ui';

interface RowConfig {
  name: LocalKeyName;
  label: string;
  placeholder: string;
  hint: string;
  maxLength: number;
  /** Optional check before saving; resolves to an error message or null. */
  validate?: (key: string) => Promise<string | null>;
}

const validateElevenLabsKey = (key: string) =>
  checkElevenLabsKey(key).then(({ status, error }) =>
    status === 'valid' ? null : status === 'invalid' ? `ElevenLabs rejected the key: ${error}` : `Could not check the key: ${error}`,
  );

const ROWS: RowConfig[] = [
  {
    name: 'elevenlabs',
    label: 'ElevenLabs',
    placeholder: 'sk_…',
    hint: 'Premium voices (and your cloned voices) billed to your ElevenLabs account instead of credits. Needs the Text to Speech and Voices read permissions.',
    maxLength: 200,
    validate: validateElevenLabsKey,
  },
  {
    name: 'openrouter',
    label: 'OpenRouter',
    placeholder: 'sk-or-…',
    hint: 'Runs the models on your OpenRouter account. Takes priority over the key saved on your account.',
    maxLength: 300,
  },
];

const LocalKeyRow = ({ row, extra }: { row: RowConfig; extra?: ReactNode }) => {
  const toast = useToast();
  const stored = useLocalKey(row.name);
  const [replacing, setReplacing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editing = !stored || replacing;

  const cancelEdit = () => {
    setReplacing(false);
    setDraft('');
    setError(null);
  };

  const save = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const key = draft.trim();
    if (!key) {
      setError(`Paste your ${row.label} key first`);
      return;
    }
    setSaving(true);
    setError(null);
    const problem = row.validate ? await row.validate(key) : null;
    setSaving(false);
    if (problem) {
      setError(problem);
      return;
    }
    setLocalKey(row.name, key);
    toast.success(`${row.label} key saved in this browser`);
    cancelEdit();
  };

  const remove = () => {
    setLocalKey(row.name, '');
    toast.info(`${row.label} key removed from this browser`);
    cancelEdit();
  };

  return (
    <div>
      <Label>{row.label}</Label>
      {editing ? (
        <form onSubmit={save} className="mt-1.5 flex gap-2">
          <Input
            type="password"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={row.placeholder}
            autoComplete="off"
            spellCheck={false}
            maxLength={row.maxLength}
            autoFocus={replacing}
            aria-label={`${row.label} API key`}
            className="min-w-0 flex-1 font-mono text-xs!"
          />
          <Button type="submit" variant="secondary" loading={saving}>
            Save
          </Button>
          {stored && <Button variant="ghost" onClick={cancelEdit} disabled={saving} aria-label="Cancel" icon={<X className="size-4" />} className="px-3" />}
        </form>
      ) : (
        <div className="mt-1.5 flex gap-2">
          <Input value={maskKey(stored)} readOnly aria-label={`Saved ${row.label} key`} className="min-w-0 flex-1 font-mono text-xs! text-text-3" />
          <Button variant="secondary" onClick={() => setReplacing(true)}>
            Replace
          </Button>
          <Button variant="danger" onClick={remove} aria-label={`Remove ${row.label} key`} icon={<Trash2 className="size-4" />} className="px-3" />
        </div>
      )}
      {error ? <Hint tone="danger">{error}</Hint> : <Hint>{row.hint}</Hint>}
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
    <div className="mt-1.5 text-xs text-muted">
      A key <span className="font-mono text-text-3">{masked}</span> is also saved on your account and is used when this browser has none.{' '}
      <button type="button" onClick={() => setConfirm(true)} className="font-semibold text-con hover:underline">
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

/** "KEYS IN THIS BROWSER": personal provider keys kept in localStorage only (lib/localKeys). */
export const LocalKeysCard = ({ user, onUser }: { user: User; onUser: (user: User) => void }) => (
  <Card>
    <SectionLabel>Keys in this browser</SectionLabel>
    <p className="mt-1.5 text-xs text-muted">
      Saved only on this device and never stored in our database: a key travels with the request that needs it and is kept in a temporary job queue for at most 24 hours.
    </p>
    <div className="mt-3.5 grid gap-4">
      {ROWS.map((row) => (
        <LocalKeyRow
          key={row.name}
          row={row}
          extra={row.name === 'openrouter' && user.openrouter_key_masked ? <AccountKeyNote masked={user.openrouter_key_masked} onUser={onUser} /> : undefined}
        />
      ))}
    </div>
  </Card>
);
