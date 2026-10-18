import { useState, type FormEvent } from 'react';
import { confirmSudo } from '../../api/admin/auth';
import { getErrorMessage } from '../../api/client';
import { FormField } from '../account/FormField';
import { Button, ErrorBox, Modal } from '../ui';

interface SudoDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after the code was accepted (the protected action is retried then). */
  onConfirmed: () => void;
}

/** Asks for a fresh authenticator code before a dangerous action. */
export const SudoDialog = ({ open, onClose, onConfirmed }: SudoDialogProps) => {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setCode('');
    setError(null);
    onClose();
  };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await confirmSudo(code);
      setCode('');
      onConfirmed();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={close} title="Confirm it is you" width="sm">
      <form onSubmit={submit} className="grid gap-4">
        <p className="text-sm leading-relaxed text-muted">Enter the current code from your authenticator app. It unlocks sensitive actions for five minutes.</p>
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
        <div className="flex justify-end gap-2">
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
