import { useState, type FormEvent } from 'react';
import { Fingerprint } from 'lucide-react';
import { confirmSudo, confirmSudoWithPasskey, sudoPasskeyOptions } from '../../api/admin/auth';
import { getPasskey, passkeysSupported } from '../../api/admin/webauthn';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { FormField } from '../account/FormField';
import { Button, ErrorBox, Modal } from '../ui';

interface SudoDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after the code was accepted (the protected action is retried then). */
  onConfirmed: () => void;
}

/** Asks for a fresh authenticator code (or a passkey) before a dangerous action. */
export const SudoDialog = ({ open, onClose, onConfirmed }: SudoDialogProps) => {
  const { me } = useAdminAuth();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passkey = Boolean(me?.passkeys) && passkeysSupported();

  const close = () => {
    setCode('');
    setError(null);
    onClose();
  };

  const confirm = async (check: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await check();
      setCode('');
      onConfirmed();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void confirm(() => confirmSudo(code));
  };

  const usePasskey = () => void confirm(async () => confirmSudoWithPasskey(await getPasskey(await sudoPasskeyOptions())));

  return (
    <Modal open={open} onClose={close} title="Confirm it is you" width="sm">
      <form onSubmit={submit} className="grid gap-4">
        <p className="text-sm leading-relaxed text-muted">
          Enter the current code from your authenticator app{passkey ? ' or use a passkey' : ''}. It unlocks sensitive actions for five minutes.
        </p>
        <FormField
          label="Authenticator code"
          className="font-mono tracking-[0.3em]"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus
          maxLength={8}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="123456"
        />
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-2">
          {passkey && (
            <Button variant="secondary" className="mr-auto" icon={<Fingerprint className="size-4" />} onClick={usePasskey} disabled={busy}>
              Use a passkey
            </Button>
          )}
          <Button variant="secondary" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" loading={busy} disabled={code.replace(/\D/g, '').length < 6}>
            Confirm
          </Button>
        </div>
      </form>
    </Modal>
  );
};
