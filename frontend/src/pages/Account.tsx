import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { confirmCheckout } from '../api/billing';
import { getErrorMessage } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { useToast } from '../components/ui';
import { useBillingConfig } from '../hooks/useBillingConfig';
import { ApiTokensCard } from '../components/account/ApiTokensCard';
import { CreditsCard } from '../components/account/CreditsCard';
import { LocalKeysCard } from '../components/account/LocalKeysCard';
import { ProfileHeader } from '../components/account/ProfileHeader';
import { SecurityCard } from '../components/account/SecurityCard';
import { TransactionsCard } from '../components/account/TransactionsCard';
import { UsageCard } from '../components/account/UsageCard';
import { money } from '../components/account/helpers';

const Account = () => {
  const { user, refresh, setUser } = useAuth();
  const { config, loaded } = useBillingConfig();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  // Stripe sends the visitor back to /account?topup=success&session_id=… (or ?topup=cancel).
  // The key guards against StrictMode's double effect run so a session is confirmed once.
  const handledTopup = useRef<string | null>(null);

  useEffect(() => {
    const topup = searchParams.get('topup');
    if (!topup) return;
    const sessionId = searchParams.get('session_id');
    const key = `${topup}:${sessionId ?? ''}`;
    if (handledTopup.current === key) return;
    handledTopup.current = key;

    const cleaned = new URLSearchParams(searchParams);
    cleaned.delete('topup');
    cleaned.delete('session_id');
    setSearchParams(cleaned, { replace: true });

    if (topup === 'cancel') {
      toast.info('Top-up cancelled. Nothing was charged.');
      return;
    }
    if (topup !== 'success') return;
    if (!sessionId) {
      // Development mode credits instantly; just pick up the new balance.
      void refresh().then(() => toast.success('Credits added to your balance'));
      return;
    }
    confirmCheckout(sessionId)
      .then((res) => {
        if (!res.credited) toast.success('Payment already credited');
        else toast.success(res.amount_usd !== null ? `Added ${money(res.amount_usd)} in credits` : 'Credits added to your balance');
      })
      .catch((err) => toast.error(getErrorMessage(err)))
      .finally(() => void refresh());
  }, [searchParams, setSearchParams, toast, refresh]);

  if (!user) return null;

  return (
    <Page>
      <ProfileHeader user={user} onUser={setUser} />
      <div className="mt-[26px] grid grid-cols-[repeat(auto-fit,minmax(min(100%,300px),1fr))] gap-3.5">
        <div className="grid content-start gap-3.5">
          <CreditsCard user={user} config={config} configLoaded={loaded} onToppedUp={() => void refresh()} />
          <SecurityCard />
        </div>
        <div className="grid content-start gap-3.5">
          <UsageCard reloadKey={user.credits_usd} />
          <LocalKeysCard user={user} onUser={setUser} />
        </div>
      </div>
      <ApiTokensCard className="mt-3.5" />
      <TransactionsCard reloadKey={user.credits_usd} className="mt-3.5" />
    </Page>
  );
};

export default Account;
