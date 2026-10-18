import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { ShieldCheck } from 'lucide-react';
import { needsSudo } from '../../api/admin/client';
import { getErrorMessage } from '../../api/client';
import { Button, ErrorBox, Hint, Modal, Textarea } from '../ui';
import { SudoDialog } from './SudoDialog';

interface ActionDialogProps {
  open: boolean;
  title: ReactNode;
  /** What happens, in a sentence or two. */
  body?: ReactNode;
  /** Fields of the action itself (amount, options…), above the reason. */
  children?: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  /** The server asks for a fresh authenticator code first (shown as a hint). */
  sudo?: boolean;
  /** Extra validity of the action's own fields. */
  ready?: boolean;
  /** Focus the reason at once (dialogs without fields of their own). */
  autoFocusReason?: boolean;
  /** Runs the change; throws to keep the dialog open with the error. */
  onSubmit: (reason: string) => Promise<void>;
  onClose: () => void;
}

/**
 * A console change: what it does, a required reason (kept in the audit log) and the button.
 * When the server answers that a fresh code is needed, the code is asked for and the same
 * change is sent again.
 */
export const ActionDialog = ({ open, title, body, children, confirmLabel, danger = false, sudo = false, ready = true, autoFocusReason = false, onSubmit, onClose }: ActionDialogProps) => {
  const reasonId = useId();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [askCode, setAskCode] = useState(false);
  const valid = reason.trim().length >= 3 && ready;

  const close = () => {
    if (busy) return;
    setReason('');
    setError(null);
    setAskCode(false);
    onClose();
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSubmit(reason.trim());
      setReason('');
      setBusy(false);
      onClose();
    } catch (err) {
      setBusy(false);
      if (needsSudo(err)) setAskCode(true);
      else setError(getErrorMessage(err));
    }
  };

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (valid && !busy) void run();
  };

  return (
    <>
      <Modal open={open && !askCode} onClose={close} title={title} width="sm">
        <form onSubmit={submit} className="grid gap-4">
          {body && <div className="text-sm leading-relaxed text-text-3">{body}</div>}
          {children}
          <div>
            <label htmlFor={reasonId} className="block text-[13px] font-semibold text-text-3">
              Reason
            </label>
            <Textarea
              id={reasonId}
              className="mt-1.5 min-h-[72px]"
              maxLength={500}
              autoFocus={autoFocusReason}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              onKeyDown={(e) => {
                // ⌘/Ctrl + Enter sends it (the moderation queue is run from the keyboard).
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && valid && !busy) {
                  e.preventDefault();
                  void run();
                }
              }}
              placeholder="Why — kept in the audit log, not shown to the user"
            />
            {sudo && (
              <Hint className="flex items-center gap-1.5">
                <ShieldCheck className="size-3.5" /> Asks for a code from your authenticator app
              </Hint>
            )}
          </div>
          {error && <ErrorBox>{error}</ErrorBox>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={close} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant={danger ? 'danger' : 'primary'} loading={busy} disabled={!valid}>
              {confirmLabel}
            </Button>
          </div>
        </form>
      </Modal>
      <SudoDialog
        open={open && askCode}
        onClose={() => setAskCode(false)}
        onConfirmed={() => {
          setAskCode(false);
          void run();
        }}
      />
    </>
  );
};
