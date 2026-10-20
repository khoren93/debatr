import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { confirmCheckout, getUsage, listTransactions } from '../api/billing';
import { getErrorMessage } from '../api/client';
import type { Transaction, Usage, User } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { Segmented, useToast } from '../components/ui';
import { useBillingConfig } from '../hooks/useBillingConfig';
import { ApiTokensCard } from '../components/account/ApiTokensCard';
import { BalanceCard } from '../components/account/BalanceCard';
import { LedgerCard, RecentActivityCard } from '../components/account/Ledger';
import { ProfileHeader } from '../components/account/ProfileHeader';
import { ProviderKeys } from '../components/account/ProviderKeys';
import { SecurityCard } from '../components/account/SecurityCard';
import { UsageCards } from '../components/account/UsageCards';
import { money } from '../components/account/helpers';
import { ACCOUNT_TABS, parseAccountTab, type AccountTab } from '../components/account/tabs';

const RECENT = 3;

/** Balance + top-up, this month's usage and the latest ledger rows. */
const Overview = ({ user, onRefresh, onTab }: { user: User; onRefresh: () => void; onTab: (tab: AccountTab) => void }) => {
  const { config, loaded } = useBillingConfig();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [recent, setRecent] = useState<Transaction[] | null>(null);
  const [recentError, setRecentError] = useState<string | null>(null);
  // A balance change (top-up, finished run) means new usage and ledger rows.
  const reloadKey = user.credits_usd;

  useEffect(() => {
    let cancelled = false;
    getUsage()
      .then((u) => {
        if (cancelled) return;
        setUsage(u);
        setUsageError(null);
      })
      .catch((err) => {
        if (!cancelled) setUsageError(getErrorMessage(err));
      });
    listTransactions(RECENT)
      .then((rows) => {
        if (cancelled) return;
        setRecent(rows);
        setRecentError(null);
      })
      .catch((err) => {
        if (!cancelled) setRecentError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return (
    <div className="grid animate-rise grid-cols-1 gap-[clamp(14px,2vw,20px)]">
      <BalanceCard user={user} config={config} configLoaded={loaded} usage={usage} onToppedUp={onRefresh} onShowKeys={() => onTab('keys')} />
      <UsageCards usage={usage} error={usageError} />
      <RecentActivityCard items={recent} error={recentError} onViewAll={() => onTab('billing')} />
    </div>
  );
};

const Account = () => {
  const { user, refresh, setUser } = useAuth();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseAccountTab(searchParams.get('tab'));
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

  const showTab = (next: AccountTab) => {
    const params = new URLSearchParams(searchParams);
    if (next === 'overview') params.delete('tab');
    else params.set('tab', next);
    setSearchParams(params, { replace: true });
  };

  if (!user) return null;

  return (
    <Page className="mx-auto grid max-w-[1080px] grid-cols-1 content-start gap-[clamp(18px,2.4vw,28px)]">
      <ProfileHeader user={user} onUser={setUser}>
        <Segmented options={ACCOUNT_TABS} value={tab} onChange={showTab} className="bg-surface!" />
      </ProfileHeader>

      {tab === 'overview' && <Overview user={user} onRefresh={() => void refresh()} onTab={showTab} />}
      {tab === 'keys' && (
        <div className="grid animate-rise grid-cols-1 gap-3.5">
          <ProviderKeys user={user} onUser={setUser} />
          <ApiTokensCard className="mt-3.5" />
        </div>
      )}
      {tab === 'billing' && (
        <div className="animate-rise">
          <LedgerCard reloadKey={user.credits_usd} />
        </div>
      )}
      {tab === 'security' && (
        <div className="animate-rise">
          <SecurityCard />
        </div>
      )}
    </Page>
  );
};

export default Account;
