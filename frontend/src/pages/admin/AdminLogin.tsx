import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, KeyRound, ShieldCheck } from 'lucide-react';
import { adminLogin, confirmEnrollment, startEnrollment, verifyAdminCode } from '../../api/admin/auth';
import type { AdminMe, EnrollStartOut } from '../../api/admin/types';
import { getErrorMessage, getErrorStatus } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { AuthLayout } from '../../components/account/AuthLayout';
import { CopyBlock } from '../../components/account/CopyBlock';
import { FormField, PasswordField } from '../../components/account/FormField';
import { RecoveryCodes } from '../../components/admin/RecoveryCodes';
import { safeAdminNext } from '../../components/admin/helpers';
import { Button, ErrorBox } from '../../components/ui';

type Step = 'password' | 'code' | 'enroll-code' | 'enroll-scan' | 'recovery';

const TITLES: Record<Step, { kicker: string; title: string; subtitle: string }> = {
  password: { kicker: 'Admin console', title: 'Sign in', subtitle: 'Your Debatr account with admin access.' },
  code: { kicker: 'Two-factor', title: 'Enter your code', subtitle: 'The 6-digit code from your authenticator app.' },
  'enroll-code': {
    kicker: 'First sign-in',
    title: 'Set up two-factor',
    subtitle: 'Enter the enrollment code that python -m app.manage admin grant printed on the server.',
  },
  'enroll-scan': {
    kicker: 'First sign-in',
    title: 'Scan the QR code',
    subtitle: 'Add it in an authenticator app (1Password, Google Authenticator, Aegis…), then enter the code it shows.',
  },
  recovery: { kicker: 'Almost done', title: 'Save your recovery codes', subtitle: 'They replace the phone if you lose it.' },
};

const SESSION_GONE = 'The sign-in timed out or had too many wrong codes. Enter your password again.';

const AdminLogin = () => {
  const { me, loading, setMe } = useAdminAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = safeAdminNext(searchParams.get('next'));
  const [step, setStep] = useState<Step>('password');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [useRecovery, setUseRecovery] = useState(false);
  const [enrollmentCode, setEnrollmentCode] = useState('');
  const [enrollment, setEnrollment] = useState<EnrollStartOut | null>(null);
  const [pending, setPending] = useState<{ me: AdminMe; codes: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!loading && me) return <Navigate to={next.startsWith('/admin') ? next : '/admin'} replace />;

  const go = (signedIn: AdminMe) => {
    setMe(signedIn);
    if (next.startsWith('/api/admin/db/')) window.location.assign(next);
    else navigate(next, { replace: true });
  };

  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      if (step !== 'password' && getErrorStatus(err) === 401) {
        setStep('password');
        setPassword('');
        setError(SESSION_GONE);
      } else {
        setError(getErrorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const submitPassword = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError('Enter your email and password');
      return;
    }
    void run(async () => {
      try {
        const out = await adminLogin(email.trim(), password);
        setCode('');
        setStep(out.next === 'totp' ? 'code' : 'enroll-code');
      } catch (err) {
        if (getErrorStatus(err) === 401) throw new Error('Wrong email or password', { cause: err });
        throw err;
      }
    });
  };

  const submitCode = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void run(async () => {
      const out = await verifyAdminCode(useRecovery ? { recovery_code: code } : { code });
      go(out.me);
    });
  };

  const submitEnrollmentCode = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void run(async () => {
      setEnrollment(await startEnrollment(enrollmentCode.trim()));
      setCode('');
      setStep('enroll-scan');
    });
  };

  const submitEnrollment = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void run(async () => {
      const out = await confirmEnrollment(code);
      setPending({ me: out.me, codes: out.recovery_codes ?? [] });
      setStep('recovery');
    });
  };

  const { kicker, title, subtitle } = TITLES[step];
  const codeField = (
    <FormField
      label={useRecovery && step === 'code' ? 'Recovery code' : 'Authenticator code'}
      inputMode={useRecovery && step === 'code' ? 'text' : 'numeric'}
      autoComplete="one-time-code"
      autoFocus
      maxLength={useRecovery ? 16 : 8}
      value={code}
      onChange={(e) => setCode(e.target.value)}
      placeholder={useRecovery && step === 'code' ? 'XXXXX-XXXXX' : '123456'}
      className="font-mono tracking-[0.2em]"
    />
  );

  return (
    <div className="flex min-h-screen flex-col bg-ink">
      <AuthLayout kicker={kicker} title={title} subtitle={subtitle}>
        {step === 'password' && (
          <form onSubmit={submitPassword} noValidate className="grid gap-4">
            <FormField label="Email" type="email" autoComplete="username" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
            <PasswordField label="Password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            {error && <ErrorBox>{error}</ErrorBox>}
            <Button type="submit" size="lg" className="mt-1 w-full" loading={busy} icon={<ArrowRight className="size-4" />}>
              Continue
            </Button>
          </form>
        )}

        {step === 'code' && (
          <form onSubmit={submitCode} noValidate className="grid gap-4">
            {codeField}
            {error && <ErrorBox>{error}</ErrorBox>}
            <Button type="submit" size="lg" className="w-full" loading={busy} icon={<ShieldCheck className="size-4" />}>
              Sign in
            </Button>
            <button
              type="button"
              onClick={() => {
                setUseRecovery((value) => !value);
                setCode('');
                setError(null);
              }}
              className="cursor-pointer text-center text-xs font-semibold text-muted hover:text-text"
            >
              {useRecovery ? 'Use the authenticator app instead' : 'Lost your phone? Use a recovery code'}
            </button>
          </form>
        )}

        {step === 'enroll-code' && (
          <form onSubmit={submitEnrollmentCode} noValidate className="grid gap-4">
            <FormField
              label="Enrollment code"
              autoFocus
              autoComplete="off"
              value={enrollmentCode}
              onChange={(e) => setEnrollmentCode(e.target.value)}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              className="font-mono tracking-[0.15em]"
              hint="Expired or lost? Run python -m app.manage admin enroll-code <email> on the server."
            />
            {error && <ErrorBox>{error}</ErrorBox>}
            <Button type="submit" size="lg" className="w-full" loading={busy} icon={<KeyRound className="size-4" />}>
              Continue
            </Button>
          </form>
        )}

        {step === 'enroll-scan' && enrollment && (
          <form onSubmit={submitEnrollment} noValidate className="grid gap-4">
            <img src={enrollment.qr} alt="QR code to add Debatr admin to an authenticator app" className="mx-auto size-52 rounded-xl bg-white p-2" />
            <div>
              <div className="text-[13px] font-semibold text-text-3">Or type the key</div>
              <CopyBlock text={enrollment.secret.replace(/(.{4})/g, '$1 ').trim()} label="Copy the key" className="mt-1.5" />
            </div>
            {codeField}
            {error && <ErrorBox>{error}</ErrorBox>}
            <Button type="submit" size="lg" className="w-full" loading={busy} icon={<ShieldCheck className="size-4" />}>
              Turn on two-factor
            </Button>
          </form>
        )}

        {step === 'recovery' && pending && (
          <div className="grid gap-4">
            <RecoveryCodes codes={pending.codes} />
            <Button size="lg" className="w-full" icon={<ArrowRight className="size-4" />} onClick={() => go(pending.me)}>
              I saved them, continue
            </Button>
          </div>
        )}
      </AuthLayout>
    </div>
  );
};

export default AdminLogin;
