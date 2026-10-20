import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Ban, CircleDollarSign, KeyRound, LockKeyhole, LogOut, Trash2, UserCheck } from 'lucide-react';
import type { AdminUserCard, CreditKind } from '../../../api/admin/types';
import {
  changeCredits,
  deleteUser,
  disableUser,
  enableUser,
  removeUserOpenRouterKey,
  setTemporaryPassword,
  signOutUser,
} from '../../../api/admin/users';
import { formatMoney } from '../../../lib/format';
import { CopyBlock } from '../../account/CopyBlock';
import { FormField } from '../../account/FormField';
import { Button, Hint, Modal, Segmented, SwitchTrack, useToast } from '../../ui';
import { ActionDialog } from '../ActionDialog';

type Dialog = 'credits' | 'disable' | 'enable' | 'sign-out' | 'password' | 'delete' | 'key';

const KINDS: { value: CreditKind; label: string; hint: string; description: string }[] = [
  { value: 'adjustment', label: 'Adjustment', hint: 'Adds or, with a minus, takes credits', description: 'Balance adjustment' },
  { value: 'bonus', label: 'Bonus', hint: 'Adds credits as a gift', description: 'Bonus credits' },
  { value: 'refund', label: 'Refund', hint: 'Gives back credits for a failed or unfair charge', description: 'Refund' },
];
const MAX_USD = 1000;

/** The amount typed in ("2.5", "-1,25"), or null when it is not a usable number. */
const parseAmount = (raw: string, kind: CreditKind): number | null => {
  const value = Number(raw.trim().replace(',', '.'));
  if (!raw.trim() || !Number.isFinite(value) || Math.abs(value) < 0.000001 || Math.abs(value) > MAX_USD) return null;
  if (kind !== 'adjustment' && value < 0) return null;
  return value;
};

const Toggle = ({ on, onChange, label, hint, disabled = false }: { on: boolean; onChange: (on: boolean) => void; label: string; hint?: string; disabled?: boolean }) => (
  <button
    type="button"
    role="switch"
    aria-checked={on}
    disabled={disabled}
    onClick={() => onChange(!on)}
    className="flex w-full cursor-pointer items-start gap-3 rounded-[12px] border border-line bg-ink px-3 py-2.5 text-left disabled:cursor-not-allowed disabled:opacity-50"
  >
    <SwitchTrack on={on} size="sm" className="mt-0.5" />
    <span className="min-w-0">
      <span className="block text-sm font-semibold text-text-2">{label}</span>
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </span>
  </button>
);

interface UserActionsProps {
  card: AdminUserCard;
  canMoney: boolean;
  /** After a change: the card loads again. */
  onChanged: () => void;
}

/** The account's action buttons and their dialogs. */
export const UserActions = ({ card, canMoney, onChanged }: UserActionsProps) => {
  const toast = useToast();
  const navigate = useNavigate();
  const user = card.profile;
  const [dialog, setDialog] = useState<Dialog | null>(null);
  // Credits
  const [kind, setKind] = useState<CreditKind>('adjustment');
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [requestKey, setRequestKey] = useState('');
  // Disable
  const [stopRuns, setStopRuns] = useState(true);
  const [revokeTokens, setRevokeTokens] = useState(false);
  const [unpublish, setUnpublish] = useState(false);
  // Delete, temporary password
  const [typedEmail, setTypedEmail] = useState('');
  const [password, setPassword] = useState<string | null>(null);

  const close = () => setDialog(null);
  const done = (message: string) => {
    toast.success(message);
    onChanged();
  };

  const openCredits = () => {
    setKind('adjustment');
    setAmount('');
    setDescription('');
    // One key per dialog: a retry or a double click never moves money twice.
    setRequestKey(crypto.randomUUID());
    setDialog('credits');
  };
  const openDisable = () => {
    setStopRuns(true);
    setRevokeTokens(false);
    setUnpublish(false);
    setDialog('disable');
  };
  const openDelete = () => {
    setTypedEmail('');
    setDialog('delete');
  };

  const value = parseAmount(amount, kind);
  const kindInfo = KINDS.find((k) => k.value === kind) ?? KINDS[0];
  const tokens = card.tokens.filter((t) => !t.expired).length;
  const lifecycle = !card.protected;

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {canMoney && (
          <Button size="sm" icon={<CircleDollarSign className="size-4" />} onClick={openCredits}>
            Credits
          </Button>
        )}
        <Button variant="secondary" size="sm" icon={<LogOut className="size-4" />} onClick={() => setDialog('sign-out')}>
          Sign out everywhere
        </Button>
        {user.openrouter_key_masked && (
          <Button variant="secondary" size="sm" icon={<KeyRound className="size-4" />} onClick={() => setDialog('key')}>
            Remove OpenRouter key
          </Button>
        )}
        {lifecycle && (
          <>
            <Button variant="secondary" size="sm" icon={<LockKeyhole className="size-4" />} onClick={() => setDialog('password')}>
              Temporary password
            </Button>
            {user.is_active ? (
              <Button variant="danger" size="sm" icon={<Ban className="size-4" />} onClick={openDisable}>
                Disable
              </Button>
            ) : (
              <Button variant="secondary" size="sm" icon={<UserCheck className="size-4" />} onClick={() => setDialog('enable')}>
                Enable
              </Button>
            )}
            <Button variant="danger" size="sm" icon={<Trash2 className="size-4" />} onClick={openDelete}>
              Delete
            </Button>
          </>
        )}
      </div>
      {!lifecycle && (
        <p className="mt-2 text-xs text-muted">
          A console account: disable, delete or reset it on the server (<code className="font-mono">python -m app.manage admin …</code>).
        </p>
      )}

      <ActionDialog
        open={dialog === 'credits'}
        title="Change credits"
        confirmLabel={value !== null && value < 0 ? 'Take credits' : 'Add credits'}
        danger={value !== null && value < 0}
        ready={value !== null}
        onClose={close}
        onSubmit={async (reason) => {
          const out = await changeCredits(user.id, {
            amount: amount.trim().replace(',', '.'),
            kind,
            reason,
            description: description.trim() || undefined,
            idempotency_key: requestKey,
          });
          done(out.duplicate ? 'Already applied: nothing changed' : `Balance is now ${formatMoney(out.balance_after)}`);
        }}
      >
        <div>
          <Segmented size="sm" options={KINDS.map((k) => ({ value: k.value, label: k.label }))} value={kind} onChange={setKind} />
          <Hint>{kindInfo.hint}. A new ledger row; history is never rewritten.</Hint>
        </div>
        <FormField
          label="Amount, USD"
          inputMode="decimal"
          autoFocus
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder={kind === 'adjustment' ? '5.00 or -2.50' : '5.00'}
          error={amount.trim() && value === null ? `A non-zero amount up to $${MAX_USD}${kind === 'adjustment' ? '' : ', positive'}` : undefined}
          hint={
            value !== null ? (
              <>
                Balance {formatMoney(user.credits_usd)} → <span className="font-semibold text-text-2">{formatMoney(user.credits_usd + value)}</span>
              </>
            ) : (
              `Balance now ${formatMoney(user.credits_usd)}`
            )
          }
        />
        <FormField
          label="What the user sees"
          optional
          maxLength={300}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={kindInfo.description}
        />
      </ActionDialog>

      <ActionDialog
        open={dialog === 'disable'}
        title="Disable the account?"
        body="Sign-ins, cookies and API tokens stop working at once. Enabling it later does not bring old sessions back."
        confirmLabel="Disable"
        danger
        onClose={close}
        onSubmit={async (reason) => {
          const out = await disableUser(user.id, { reason, stop_debates: stopRuns, revoke_tokens: revokeTokens, unpublish });
          const parts = [out.stopped && `${out.stopped} stopped`, out.tokens_revoked && `${out.tokens_revoked} tokens revoked`, out.unpublished && `${out.unpublished} unpublished`].filter(Boolean);
          done(`Account disabled${parts.length ? ` (${parts.join(', ')})` : ''}`);
        }}
      >
        <div className="grid gap-2">
          <Toggle on={stopRuns} onChange={setStopRuns} label="Stop running debates" hint={`${card.active_debates} queued or running`} disabled={!card.active_debates} />
          <Toggle on={revokeTokens} onChange={setRevokeTokens} label="Revoke API tokens" hint={`${tokens} working token${tokens === 1 ? '' : 's'}; they would need new ones`} disabled={!card.tokens.length} />
          <Toggle on={unpublish} onChange={setUnpublish} label="Take public debates out of the gallery" hint={`${card.public_debates} public`} disabled={!card.public_debates} />
        </div>
      </ActionDialog>

      <ActionDialog
        open={dialog === 'enable'}
        title="Enable the account?"
        body="The user can sign in again with their password; API tokens that were not revoked work again."
        confirmLabel="Enable"
        onClose={close}
        onSubmit={async (reason) => {
          await enableUser(user.id, reason);
          done('Account enabled');
        }}
      />

      <ActionDialog
        open={dialog === 'sign-out'}
        title="Sign out everywhere?"
        body="Every browser signed in to this account has to sign in again. API tokens keep working (revoke them below)."
        confirmLabel="Sign out everywhere"
        danger
        onClose={close}
        onSubmit={async (reason) => {
          await signOutUser(user.id, reason);
          done('Every session of the account ended');
        }}
      />

      <ActionDialog
        open={dialog === 'key'}
        title="Remove the stored OpenRouter key?"
        body={`The key ${user.openrouter_key_masked ?? ''} is deleted; their runs use credits again until they add a key.`}
        confirmLabel="Remove key"
        danger
        onClose={close}
        onSubmit={async (reason) => {
          await removeUserOpenRouterKey(user.id, reason);
          done('OpenRouter key removed');
        }}
      />

      <ActionDialog
        open={dialog === 'password'}
        title="Set a temporary password?"
        body="The current password stops working and every session ends. You see the new one once: pass it on over a channel you trust and ask them to change it on the Account page."
        confirmLabel="Set password"
        danger
        sudo
        onClose={close}
        onSubmit={async (reason) => {
          setPassword(await setTemporaryPassword(user.id, reason));
          onChanged();
        }}
      />
      <Modal open={password !== null} onClose={() => setPassword(null)} title="Temporary password" width="sm">
        {password && (
          <div className="grid gap-3">
            <p className="text-sm text-text-3">
              For <span className="font-semibold text-text-2">{user.email}</span>. It is not shown again.
            </p>
            <CopyBlock text={password} label="Copy password" />
          </div>
        )}
      </Modal>

      <ActionDialog
        open={dialog === 'delete'}
        title="Delete the account?"
        body={
          <>
            This cannot be undone. Gone with it: {card.all_time.debates} debates with their audio and pictures, the ledger, API tokens and the likes and votes it gave. The audit log keeps a
            record.
          </>
        }
        confirmLabel="Delete for good"
        danger
        sudo
        ready={typedEmail.trim().toLowerCase() === user.email}
        onClose={close}
        onSubmit={async (reason) => {
          const debates = await deleteUser(user.id, reason, typedEmail.trim());
          toast.success(`Deleted ${user.email} and ${debates} debate${debates === 1 ? '' : 's'}`);
          navigate('/admin/users', { replace: true });
        }}
      >
        <FormField label={`Type ${user.email} to confirm`} autoComplete="off" value={typedEmail} onChange={(e) => setTypedEmail(e.target.value)} />
      </ActionDialog>
    </>
  );
};
