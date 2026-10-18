import { useEffect, useState, type FormEvent } from 'react';
import { Cloud, Fingerprint, Plus } from 'lucide-react';
import { addPasskey, listPasskeys, passkeyAddOptions, removePasskey } from '../../api/admin/auth';
import { needsSudo } from '../../api/admin/client';
import type { AdminPasskey } from '../../api/admin/types';
import { createPasskey, passkeysSupported } from '../../api/admin/webauthn';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { FormField } from '../account/FormField';
import { Button, Card, ConfirmDialog, ErrorBox, Modal, SectionLabel, Spinner, useToast } from '../ui';
import { SudoDialog } from './SudoDialog';
import { describeAgent, formatTime } from './helpers';

/** The admin's passkeys: sign in and confirm sudo without typing a code. */
export const PasskeysCard = () => {
  const { me, refresh } = useAdminAuth();
  const toast = useToast();
  const supported = passkeysSupported();
  const [rows, setRows] = useState<AdminPasskey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [addError, setAddError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<AdminPasskey | null>(null);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState<(() => Promise<void>) | null>(null);

  useEffect(() => {
    let cancelled = false;
    listPasskeys()
      .then((found) => {
        if (!cancelled) setRows(found);
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const changed = async (message: string) => {
    toast.success(message);
    setReload((n) => n + 1);
    await refresh();
  };

  // Runs a change that may need sudo first: the code dialog opens and the change runs again.
  const guarded = async (action: () => Promise<void>, onError: (message: string) => void) => {
    setBusy(true);
    try {
      await action();
    } catch (err) {
      if (needsSudo(err)) setRetry(() => action);
      else onError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  // Sudo before the name dialog: the browser then asks for the passkey right after the click
  // on "Create passkey" (Safari refuses WebAuthn calls too far from a click).
  const sudoFresh = () => !me?.two_factor || (me.session.sudo_until !== null && new Date(me.session.sudo_until).getTime() > Date.now() + 30_000);
  const startAdd = () => {
    setName(describeAgent(navigator.userAgent));
    setAddError(null);
    if (sudoFresh()) setNaming(true);
    else setRetry(() => async () => setNaming(true));
  };

  const add = async () => {
    const credential = await createPasskey(await passkeyAddOptions());
    const row = await addPasskey(name.trim(), credential);
    setNaming(false);
    setName('');
    await changed(`Passkey “${row.name}” added`);
  };

  const submitName = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setAddError(null);
    void guarded(add, setAddError);
  };

  const remove = async () => {
    if (!removing) return;
    const target = removing;
    await removePasskey(target.id);
    setRemoving(null);
    await changed(`Passkey “${target.name}” removed`);
  };

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionLabel>Passkeys</SectionLabel>
        {supported && (
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus className="size-4" />}
            onClick={startAdd}
          >
            Add a passkey
          </Button>
        )}
      </div>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        Touch ID, Windows Hello, a phone or a security key instead of the 6-digit code, at sign-in and for confirmations. The authenticator app and recovery codes keep working.
      </p>
      {!supported && <p className="mt-3 text-sm text-text-3">This browser cannot use passkeys.</p>}
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!rows && !error && <Spinner className="mt-6 size-5" />}
      {rows && rows.length === 0 && <p className="mt-4 text-sm text-text-3">No passkeys yet.</p>}
      {rows && rows.length > 0 && (
        <ul className="mt-3 divide-y divide-line">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center gap-3 py-3">
              <Fingerprint className="size-5 shrink-0 text-muted" strokeWidth={1.6} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <span className="truncate">{row.name}</span>
                  {row.backed_up && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-bold uppercase text-muted" title="Synced between your devices">
                      <Cloud className="size-3" /> Synced
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-xs text-muted">
                  added {formatTime(row.created_at)} · {row.last_used_at ? `used ${formatTime(row.last_used_at)}` : 'never used'}
                </div>
              </div>
              <Button variant="secondary" size="sm" onClick={() => setRemoving(row)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}

      <Modal open={naming} onClose={() => !busy && setNaming(false)} title="Add a passkey" width="sm">
        <form onSubmit={submitName} className="grid gap-4">
          <FormField label="Name" autoFocus maxLength={64} value={name} onChange={(e) => setName(e.target.value)} hint="To tell your passkeys apart, e.g. “MacBook Touch ID”." />
          {addError && <ErrorBox>{addError}</ErrorBox>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setNaming(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" loading={busy} disabled={!name.trim()} icon={<Fingerprint className="size-4" />}>
              Create passkey
            </Button>
          </div>
        </form>
      </Modal>
      <ConfirmDialog
        open={removing !== null}
        title="Remove this passkey?"
        body={`“${removing?.name ?? ''}” will no longer sign you in. Remove it from the device or password manager too.`}
        confirmLabel="Remove"
        danger
        busy={busy}
        onConfirm={() => void guarded(remove, (message) => toast.error(message))}
        onClose={() => setRemoving(null)}
      />
      <SudoDialog
        open={retry !== null}
        onClose={() => setRetry(null)}
        onConfirmed={() => {
          const action = retry;
          setRetry(null);
          void refresh(); // the session's new sudo deadline
          if (action) void guarded(action, (message) => (naming ? setAddError(message) : toast.error(message)));
        }}
      />
    </Card>
  );
};
