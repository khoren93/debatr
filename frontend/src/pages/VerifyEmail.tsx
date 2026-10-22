import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { CircleAlert, CircleCheck } from 'lucide-react';
import { verifyEmail } from '../api/auth';
import { getErrorMessage } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AuthLayout } from '../components/account/AuthLayout';
import { accountPath } from '../components/account/tabs';
import { LinkButton, Spinner } from '../components/ui';

type Result = { ok: true; published: number } | { ok: false; message: string };

/** The page a confirmation link opens (`?token=`). The page posts the token itself, so mail
 *  scanners that only fetch the link confirm nothing; posting it twice is harmless. */
const VerifyEmail = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';
  const { user, refresh } = useAuth();
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    verifyEmail(token)
      .then((res) => {
        if (cancelled) return;
        setResult({ ok: true, published: res.published });
        void refresh();
      })
      .catch((err: unknown) => {
        if (!cancelled) setResult({ ok: false, message: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [token, refresh]);

  const next = user ? (
    <LinkButton to="/library" size="lg" className="w-full">
      Go to my library
    </LinkButton>
  ) : (
    <LinkButton to="/login" size="lg" className="w-full">
      Sign in
    </LinkButton>
  );

  if (!token || (result && !result.ok)) {
    return (
      <AuthLayout kicker="Confirm email" title="This link did not work">
        <div className="flex gap-3 text-sm leading-relaxed text-text-3">
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-con" />
          <p>
            {result && !result.ok ? result.message : 'The link is incomplete.'} {user ? 'Ask for a new one under Account → Security.' : 'Sign in to ask for a new one.'}
          </p>
        </div>
        <div className="mt-5">
          {user ? (
            <LinkButton to={accountPath('security')} size="lg" className="w-full">
              Open Security
            </LinkButton>
          ) : (
            next
          )}
        </div>
      </AuthLayout>
    );
  }

  if (!result) {
    return (
      <AuthLayout kicker="Confirm email" title="Confirming…">
        <Spinner className="size-6" />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout kicker="Confirm email" title="Email confirmed">
      <div className="flex gap-3 text-sm leading-relaxed text-text-3">
        <CircleCheck className="mt-0.5 size-5 shrink-0 text-ok" />
        <p>
          Thanks! You can now publish debates to the gallery and add credits.
          {result.published > 0 && ` ${result.published === 1 ? 'Your debate that waited for it is' : `${result.published} debates that waited for it are`} public now.`}
        </p>
      </div>
      <div className="mt-5">
        {next}
        <Link to="/" className="mt-3 block text-center text-sm text-muted hover:text-text">
          Back to Debatr
        </Link>
      </div>
    </AuthLayout>
  );
};

export default VerifyEmail;
