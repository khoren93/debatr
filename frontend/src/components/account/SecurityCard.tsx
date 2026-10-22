import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { CircleCheck, LogOut } from 'lucide-react';
import { changePassword, resendConfirmation } from '../../api/auth';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { Button, Input, useToast } from '../ui';
import { describeDevice } from './helpers';

const MIN_PASSWORD = 8;
const ROW = 'flex flex-wrap items-center gap-4 p-[clamp(18px,2.6vw,24px)]';

/** The account's email and whether it is confirmed (a new link on request). */
const EmailRow = () => {
  const { user } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  if (!user) return null;
  const resend = async () => {
    setBusy(true);
    try {
      await resendConfirmation();
      setSent(true);
      toast.success(`Sent a link to ${user.email}`);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={`${ROW} border-b border-line`}>
      <div className="min-w-[200px] flex-1">
        <div className="text-[15px] font-bold">Email</div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[13px] text-muted">
          <span className="text-text-2">{user.email}</span>
          {user.email_verified ? (
            <span className="inline-flex items-center gap-1 text-ok">
              <CircleCheck className="size-3.5" /> Confirmed
            </span>
          ) : (
            <span className="text-host">{user.email_required ? 'Not confirmed: publishing and top-ups wait for it' : 'Not confirmed'}</span>
          )}
        </div>
      </div>
      {!user.email_verified && (
        <Button variant="secondary" size="sm" onClick={resend} loading={busy} disabled={sent}>
          {sent ? 'Link sent' : 'Send a link'}
        </Button>
      )}
    </div>
  );
};

/** Email (confirmation), password (inline change form) and the current session with sign out. */
export const SecurityCard = () => {
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const device = describeDevice(navigator.userAgent);

  const toggle = () => {
    setOpen(!open);
    setCurrent('');
    setNext('');
    setError(null);
  };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!current) {
      setError('Enter your current password');
      return;
    }
    if (next.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters for the new password`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      toast.success('Password changed');
      setOpen(false);
      setCurrent('');
      setNext('');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const doSignOut = async () => {
    setSigningOut(true);
    try {
      await signOut();
    } catch {
      // The session cookie is gone either way; the context already cleared the user.
    }
    navigate('/');
  };

  return (
    <div className="rounded-panel border border-line bg-surface">
      <EmailRow />
      <div className={`${ROW} border-b border-line`}>
        <div className="min-w-[200px] flex-1">
          <div className="text-[15px] font-bold">Password</div>
          <div className="mt-1 text-[13px] text-muted">Use at least {MIN_PASSWORD} characters. You'll stay signed in here.</div>
        </div>
        <Button variant="secondary" size="sm" onClick={toggle} disabled={busy} aria-expanded={open}>
          {open ? 'Cancel' : 'Change'}
        </Button>
        {open && (
          <form onSubmit={submit} noValidate className="basis-full">
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,200px),1fr))] gap-2">
              <Input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                placeholder="Current password"
                aria-label="Current password"
                autoComplete="current-password"
                autoFocus
              />
              <Input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                placeholder="New password"
                aria-label="New password"
                autoComplete="new-password"
                maxLength={72}
              />
              <Button type="submit" loading={busy}>
                Update password
              </Button>
            </div>
            {error && <div className="mt-2.5 text-xs text-con">{error}</div>}
          </form>
        )}
      </div>
      <div className={ROW}>
        <div className="min-w-[200px] flex-1">
          <div className="text-[15px] font-bold">Session</div>
          <div className="mt-1 text-[13px] text-muted">Signed in on this device{device ? ` · ${device}` : ''}</div>
        </div>
        <Button
          variant="danger"
          size="sm"
          onClick={doSignOut}
          loading={signingOut}
          icon={<LogOut className="size-3.5" />}
          className="border-con/40! bg-transparent! hover:bg-con/8!"
        >
          Sign out
        </Button>
      </div>
    </div>
  );
};
