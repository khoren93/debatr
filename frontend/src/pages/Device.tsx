import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Check, CheckCircle2, Terminal, X, XCircle } from 'lucide-react';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { approveDevice, denyDevice, getDeviceRequest } from '../api/tokens';
import type { DeviceRequest } from '../api/types';
import { AuthLayout } from '../components/account/AuthLayout';
import { accountPath } from '../components/account/tabs';
import { FormField } from '../components/account/FormField';
import { tokenRequest, type TokenOptions } from '../components/account/tokenOptions';
import { TokenOptionsFields } from '../components/account/TokenOptionsFields';
import { Button, ErrorBox, Spinner } from '../components/ui';

/** "wdjb mjht" -> "WDJB-MJHT" (the backend accepts any spacing too). */
const tidyCode = (raw: string) => {
  const chars = raw.toUpperCase().replace(/[^A-Z0-9]/g, '');
  return chars.length > 4 ? `${chars.slice(0, 4)}-${chars.slice(4, 8)}` : chars;
};

const CAN = ['Start, follow, stop and publish debates', 'Spend your credits, up to the limit you set', 'Read your balance and debates'];
const CANNOT = ['Change your password or stored keys', 'Buy credits or create other tokens'];

const Cmd = ({ children }: { children: string }) => <span className="font-mono text-text-3">{children}</span>;

type Lookup = { code: string; request: DeviceRequest | null; error: string | null };
type Outcome = 'approved' | 'denied';

/** Step 1 without a code in the link: type the code shown in the terminal. */
const CodeForm = ({ onCode }: { onCode: (code: string) => void }) => {
  const [value, setValue] = useState('');
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (value.replace(/[^a-z0-9]/gi, '').length === 8) onCode(tidyCode(value));
  };
  return (
    <AuthLayout
      kicker="Connect a device"
      title="Enter the code"
      subtitle={
        <>
          Type the code that <Cmd>debatr login</Cmd> shows in your terminal.
        </>
      }
    >
      <form onSubmit={submit} className="grid gap-4">
        <FormField
          label="Code"
          value={value}
          onChange={(e) => setValue(tidyCode(e.target.value))}
          placeholder="XXXX-XXXX"
          autoFocus
          autoComplete="off"
          spellCheck={false}
          maxLength={9}
          className="font-mono text-lg! tracking-[0.2em] uppercase"
        />
        <Button type="submit" size="lg" disabled={value.length !== 9}>
          Continue
        </Button>
      </form>
    </AuthLayout>
  );
};

const Done = ({ outcome }: { outcome: Outcome }) =>
  outcome === 'approved' ? (
    <AuthLayout kicker="Connect a device" title="Device connected" subtitle="Go back to your terminal: the CLI is signed in. You can close this tab.">
      <div className="flex items-center gap-3 rounded-field border border-ok/30 bg-ok/10 px-4 py-3 text-sm text-text-2">
        <CheckCircle2 className="size-5 shrink-0 text-ok" />
        The token is listed under Account → API keys, where you can revoke it at any time.
      </div>
      <Link to={accountPath('keys')} className="mt-4 inline-block text-sm font-semibold text-accent hover:text-accent-hover">
        Manage tokens
      </Link>
    </AuthLayout>
  ) : (
    <AuthLayout
      kicker="Connect a device"
      title="Request denied"
      subtitle={
        <>
          Nothing was connected. If you did not run <Cmd>debatr login</Cmd> yourself, you were right to deny it.
        </>
      }
    >
      <div className="flex items-center gap-3 rounded-field border border-line-2 bg-surface-2 px-4 py-3 text-sm text-text-3">
        <XCircle className="size-5 shrink-0 text-muted" />
        The terminal shows that the request was denied.
      </div>
    </AuthLayout>
  );

/** /device?code=WDJB-MJHT: approve or deny a `debatr login` from the terminal. */
const Device = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const code = tidyCode(searchParams.get('code') ?? '');
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [options, setOptions] = useState<TokenOptions | null>(null);
  const [busy, setBusy] = useState<'approve' | 'deny' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (code.length !== 9) return;
    let cancelled = false;
    getDeviceRequest(code)
      .then((request) => {
        if (!cancelled) setLookup({ code, request, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        const message = getErrorStatus(err) === 404 ? 'This code is invalid or has expired.' : getErrorMessage(err);
        setLookup({ code, request: null, error: message });
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (outcome) return <Done outcome={outcome} />;
  if (code.length !== 9) return <CodeForm onCode={(next) => setSearchParams({ code: next }, { replace: true })} />;

  const current = lookup?.code === code ? lookup : null;
  if (!current) {
    return (
      <AuthLayout kicker="Connect a device" title="Checking the code…">
        <div className="flex justify-center py-6">
          <Spinner className="size-6" />
        </div>
      </AuthLayout>
    );
  }
  const request = current.request;
  if (!request || request.status !== 'pending') {
    return (
      <AuthLayout
        kicker="Connect a device"
        title={request ? 'Already answered' : 'Code not found'}
        subtitle={request ? 'This request was already approved or denied.' : (current.error ?? 'This code is invalid or has expired.')}
      >
        <p className="text-sm text-muted">
          Run <Cmd>debatr login</Cmd> again in your terminal to get a fresh code.
        </p>
      </AuthLayout>
    );
  }

  const form = options ?? { name: request.client_name, expiry: 'never', limit: '' };

  const approve = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const body = tokenRequest(form);
    if (body.error !== undefined) {
      setError(body.error);
      return;
    }
    setBusy('approve');
    setError(null);
    try {
      await approveDevice(code, body.body);
      setOutcome('approved');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const deny = async () => {
    setBusy('deny');
    setError(null);
    try {
      await denyDevice(code);
      setOutcome('denied');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <AuthLayout
      kicker="Connect a device"
      title="Allow this terminal?"
      subtitle={
        <>
          <span className="font-semibold text-text-2">{request.client_name}</span> wants to use Debatr as you.
        </>
      }
    >
      <form onSubmit={approve} noValidate className="grid gap-5">
        <div className="rounded-field border border-accent/30 bg-accent/5 px-4 py-3">
          <div className="flex items-center gap-2 text-xs text-muted">
            <Terminal className="size-3.5" /> Check that your terminal shows the same code
          </div>
          <div className="mt-1.5 font-mono text-2xl font-bold tracking-[0.18em] text-accent">{request.user_code}</div>
        </div>

        <div className="grid gap-1.5 text-[13px]">
          {CAN.map((line) => (
            <div key={line} className="flex items-start gap-2 text-text-3">
              <Check className="mt-0.5 size-4 shrink-0 text-ok" /> {line}
            </div>
          ))}
          {CANNOT.map((line) => (
            <div key={line} className="flex items-start gap-2 text-muted">
              <X className="mt-0.5 size-4 shrink-0 text-dim" /> {line}
            </div>
          ))}
        </div>

        <TokenOptionsFields value={form} onChange={setOptions} />
        {error && <ErrorBox>{error}</ErrorBox>}

        <div className="grid grid-cols-2 gap-2.5">
          <Button variant="secondary" size="lg" onClick={deny} loading={busy === 'deny'} disabled={busy !== null}>
            Deny
          </Button>
          <Button type="submit" size="lg" loading={busy === 'approve'} disabled={busy !== null}>
            Allow
          </Button>
        </div>
      </form>
    </AuthLayout>
  );
};

export default Device;
