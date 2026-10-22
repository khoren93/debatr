import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ArrowRight } from 'lucide-react';
import { resetPassword } from '../api/auth';
import { getErrorMessage } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthLayout } from '../components/account/AuthLayout';
import { PasswordField } from '../components/account/FormField';
import { Button, ErrorBox, useToast } from '../components/ui';

const MIN_PASSWORD = 8;

/** The page a reset link opens (`?token=`): a new password, then signed in. */
const ResetPassword = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    if (password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setUser(await resetPassword(token, password));
      toast.success('Password changed. Other devices were signed out.');
      navigate('/library', { replace: true });
    } catch (err) {
      setError(getErrorMessage(err));
      setBusy(false);
    }
  };

  const footer = (
    <Link to="/forgot-password" className="font-semibold text-accent hover:text-accent-hover">
      Ask for a new link
    </Link>
  );

  if (!token) {
    return (
      <AuthLayout kicker="Reset password" title="This link is incomplete" subtitle="Open the link from the email again, or ask for a new one." footer={footer}>
        {null}
      </AuthLayout>
    );
  }

  return (
    <AuthLayout kicker="Reset password" title="Set a new password" subtitle="Other devices will be signed out." footer={footer}>
      <form onSubmit={onSubmit} noValidate className="grid gap-4">
        <PasswordField label="New password" autoComplete="new-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} hint={`At least ${MIN_PASSWORD} characters`} />
        {error && <ErrorBox>{error}</ErrorBox>}
        <Button type="submit" size="lg" className="mt-1 w-full" loading={busy} icon={<ArrowRight className="size-4" />}>
          Save and sign in
        </Button>
      </form>
    </AuthLayout>
  );
};

export default ResetPassword;
