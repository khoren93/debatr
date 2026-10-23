import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router';
import { ArrowRight } from 'lucide-react';
import { register } from '../api/auth';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthLayout } from '../components/account/AuthLayout';
import { FormField, PasswordField } from '../components/account/FormField';
import { GoogleSignIn } from '../components/account/GoogleButton';
import { money, safeNext, withNext } from '../components/account/helpers';
import { Button, ErrorBox, LinkButton, useToast } from '../components/ui';
import { useBillingConfig } from '../hooks/useBillingConfig';
import { useSiteStatus } from '../hooks/useSiteStatus';
import { APP_NAME } from '../lib/brand';
import { track } from '../lib/presence';

const DEFAULT_NEXT = '/library';
const MIN_PASSWORD = 8;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Field = 'email' | 'password' | 'confirm';
const UNTOUCHED: Record<Field, boolean> = { email: false, password: false, confirm: false };
const ALL_TOUCHED: Record<Field, boolean> = { email: true, password: true, confirm: true };

const Register = () => {
  const { user, loading, setUser } = useAuth();
  const { config } = useBillingConfig();
  const site = useSiteStatus();
  const toast = useToast();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = safeNext(searchParams.get('next'));
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [touched, setTouched] = useState(UNTOUCHED);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exists, setExists] = useState(false);

  const bonus = config.signup_bonus_usd;
  const emailError = EMAIL_RE.test(email.trim()) ? null : 'Enter a valid email address';
  const passwordError = password.length >= MIN_PASSWORD ? null : `Use at least ${MIN_PASSWORD} characters`;
  const confirmError = confirm === password ? null : 'Passwords do not match';
  const valid = !emailError && !passwordError && !confirmError;

  if (!loading && user) return <Navigate to={next ?? DEFAULT_NEXT} replace />;
  if (!site.registration_open) {
    return (
      <AuthLayout kicker="Get started" title="Sign-ups are closed for now" subtitle="New accounts are paused for a while. Accounts that exist can still sign in.">
        <LinkButton to={withNext('/login', next)} size="lg" className="w-full" icon={<ArrowRight className="size-4" />}>
          Sign in
        </LinkButton>
      </AuthLayout>
    );
  }

  const touch = (field: Field) => setTouched((t) => (t[field] ? t : { ...t, [field]: true }));

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    if (!valid) {
      setTouched(ALL_TOUCHED);
      return;
    }
    setBusy(true);
    setError(null);
    setExists(false);
    try {
      setUser(await register(email.trim(), password, name.trim() || undefined));
      track('signup');
      toast.success(bonus > 0 ? `Welcome! ${money(bonus)} of credits added` : `Welcome to ${APP_NAME}!`);
      navigate(next ?? DEFAULT_NEXT, { replace: true });
    } catch (err) {
      if (getErrorStatus(err) === 409) setExists(true);
      else setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      kicker="Get started"
      title="Create your account"
      subtitle={
        bonus > 0
          ? `New accounts start with ${money(bonus)} of free credits — enough for your first debates.`
          : 'Run debates, keep a library and render videos right in your browser.'
      }
      footer={
        <>
          Already have an account?{' '}
          <Link to={withNext('/login', next)} className="font-semibold text-accent hover:text-accent-hover">
            Sign in
          </Link>
          <span className="mt-2 block text-[11px] text-dim">
            How we handle data:{' '}
            <Link to="/privacy" className="hover:text-muted">
              Privacy
            </Link>
          </span>
        </>
      }
    >
      {site.google_login && (
        <div className="mb-4">
          <GoogleSignIn next={next} />
        </div>
      )}
      <form onSubmit={onSubmit} noValidate className="grid gap-4">
        <FormField label="Name" optional autoComplete="name" autoFocus={!site.google_login} value={name} onChange={(e) => setName(e.target.value)} placeholder="How should we call you?" maxLength={60} />
        <FormField
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onBlur={() => touch('email')}
          placeholder="you@example.com"
          error={touched.email ? emailError : null}
        />
        <PasswordField
          label="Password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onBlur={() => touch('password')}
          hint={`At least ${MIN_PASSWORD} characters`}
          error={touched.password ? passwordError : null}
        />
        <PasswordField
          label="Confirm password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          onBlur={() => touch('confirm')}
          error={touched.confirm ? confirmError : null}
        />
        {exists && (
          <ErrorBox>
            An account with this email already exists.{' '}
            <Link to={withNext('/login', next)} className="font-semibold underline hover:text-text">
              Sign in instead
            </Link>
          </ErrorBox>
        )}
        {error && <ErrorBox>{error}</ErrorBox>}
        <Button type="submit" size="lg" className="mt-1 w-full" loading={busy} icon={<ArrowRight className="size-4" />}>
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
};

export default Register;
