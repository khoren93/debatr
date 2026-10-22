import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { ArrowRight, MailCheck } from 'lucide-react';
import { forgotPassword } from '../api/auth';
import { getErrorMessage } from '../api/client';
import { AuthLayout } from '../components/account/AuthLayout';
import { FormField } from '../components/account/FormField';
import { Button, ErrorBox } from '../components/ui';

const BackToSignIn = () => (
  <Link to="/login" className="font-semibold text-accent hover:text-accent-hover">
    Back to sign in
  </Link>
);

/** "Forgot password?": mails a reset link. Says the same whether the account exists or not. */
const ForgotPassword = () => {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    const address = email.trim();
    if (!address) {
      setError('Enter the email of your account');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await forgotPassword(address);
      setSentTo(address);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (sentTo) {
    return (
      <AuthLayout kicker="Check your inbox" title="Link on its way" footer={<BackToSignIn />}>
        <div className="flex gap-3 text-sm leading-relaxed text-text-3">
          <MailCheck className="mt-0.5 size-5 shrink-0 text-accent" />
          <p>
            If <span className="font-semibold text-text">{sentTo}</span> has an account, a link to set a new password is in its inbox now. It works for an hour, once. Nothing there?
            Look in spam, or try again in a few minutes.
          </p>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout kicker="Forgot password" title="Reset your password" subtitle="We will email you a link to set a new one." footer={<BackToSignIn />}>
      <form onSubmit={onSubmit} noValidate className="grid gap-4">
        <FormField label="Email" type="email" autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        {error && <ErrorBox>{error}</ErrorBox>}
        <Button type="submit" size="lg" className="mt-1 w-full" loading={busy} icon={<ArrowRight className="size-4" />}>
          Send the link
        </Button>
      </form>
    </AuthLayout>
  );
};

export default ForgotPassword;
