import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router';
import { ArrowRight } from 'lucide-react';
import { login } from '../api/auth';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthLayout } from '../components/account/AuthLayout';
import { FormField, PasswordField } from '../components/account/FormField';
import { safeNext, withNext } from '../components/account/helpers';
import { Button, ErrorBox } from '../components/ui';
import { track } from '../lib/presence';

const DEFAULT_NEXT = '/library';

const Login = () => {
  const { user, loading, setUser } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = safeNext(searchParams.get('next'));
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already signed in (e.g. the back button after logging in): skip the form.
  if (!loading && user) return <Navigate to={next ?? DEFAULT_NEXT} replace />;

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    if (!email.trim() || !password) {
      setError('Enter your email and password');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setUser(await login(email.trim(), password));
      track('login');
      navigate(next ?? DEFAULT_NEXT, { replace: true });
    } catch (err) {
      setError(getErrorStatus(err) === 401 ? 'Wrong email or password' : getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout
      kicker="Welcome back"
      title="Sign in"
      subtitle="Your library, credits and keys are right where you left them."
      footer={
        <>
          No account?{' '}
          <Link to={withNext('/register', next)} className="font-semibold text-accent hover:text-accent-hover">
            Create one
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="grid gap-4">
        <FormField
          label="Email"
          type="email"
          autoComplete="email"
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
        />
        <PasswordField label="Password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <Link to="/forgot-password" className="-mt-2 justify-self-end text-[13px] text-muted transition-colors hover:text-text">
          Forgot password?
        </Link>
        {error && <ErrorBox>{error}</ErrorBox>}
        <Button type="submit" size="lg" className="mt-1 w-full" loading={busy} icon={<ArrowRight className="size-4" />}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
};

export default Login;
