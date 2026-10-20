import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router';
import { ArrowLeft, KeyRound, ShieldCheck } from 'lucide-react';
import type { AdminUserCard } from '../../api/admin/types';
import { getUserCard } from '../../api/admin/users';
import { getErrorMessage } from '../../api/client';
import { useAdminAuth } from '../../auth/AdminAuthContext';
import { Page } from '../../components/layout/AppShell';
import { UserActions } from '../../components/admin/users/UserActions';
import { UserBadges } from '../../components/admin/users/UserBadges';
import { AuditPanel, DebatesPanel, FavoriteModels, LedgerPanel, ReactionsPanel, SpendChart, StatsGrid, TokensPanel } from '../../components/admin/users/UserSections';
import { formatTime } from '../../components/admin/helpers';
import { Avatar, Card, ErrorBox, SectionLabel, Segmented, Spinner } from '../../components/ui';
import { formatAgo, formatMoney } from '../../lib/format';

type Period = '30d' | 'all';

const Fact = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="min-w-0">
    <div className="text-[11px] text-muted">{label}</div>
    <div className="truncate text-[13px] text-text-2">{children}</div>
  </div>
);

const AdminUser = () => {
  const { id = '' } = useParams();
  const { me } = useAdminAuth();
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{ key: string; card: AdminUserCard } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>('30d');
  const key = `${id}:${version}`;

  useEffect(() => {
    let cancelled = false;
    getUserCard(id)
      .then((card) => {
        if (!cancelled) {
          setResult({ key: `${id}:${version}`, card });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [id, version]);

  if (!me) return null;
  const card = result?.card.profile.id === id ? result.card : null;
  const reload = () => setVersion((n) => n + 1);
  const canMoney = me.permissions.includes('money');

  return (
    <Page>
      <Link to="/admin/users" className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-text">
        <ArrowLeft className="size-3.5" /> Users
      </Link>
      {error && <ErrorBox className="mt-4">{error}</ErrorBox>}
      {!card && !error && <Spinner className="mt-10 size-6" />}

      {card && (
        <div className={`transition-opacity ${result?.key !== key ? 'opacity-60' : ''}`}>
          <Card className="mt-4">
            <div className="flex flex-wrap items-start gap-4">
              <Avatar seed={card.profile.avatar_seed || card.profile.id} size={52} rounded="lg" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="truncate font-display text-2xl font-extrabold tracking-tight">{card.profile.display_name}</h1>
                  <UserBadges role={card.profile.role} active={card.profile.is_active} />
                </div>
                <div className="truncate text-sm text-muted">{card.profile.email}</div>
              </div>
              <div className="text-right">
                <SectionLabel>Balance</SectionLabel>
                <div className={`font-display text-3xl font-bold tracking-tight ${card.profile.credits_usd < 0 ? 'text-con' : ''}`}>{formatMoney(card.profile.credits_usd)}</div>
              </div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-4 sm:grid-cols-3 lg:grid-cols-6">
              <Fact label="Signed up">{formatTime(card.profile.created_at)}</Fact>
              <Fact label="Last seen">{card.profile.last_seen_at ? `${formatAgo(card.profile.last_seen_at)}, ${formatTime(card.profile.last_seen_at)}` : 'never'}</Fact>
              <Fact label="Last sign-in">{card.profile.last_login_at ? formatTime(card.profile.last_login_at) : 'never'}</Fact>
              <Fact label="OpenRouter key">
                {card.profile.openrouter_key_masked ? (
                  <span className="inline-flex items-center gap-1 font-mono">
                    <KeyRound className="size-3.5 text-muted" /> {card.profile.openrouter_key_masked}
                  </span>
                ) : (
                  'none'
                )}
              </Fact>
              <Fact label="Console">
                {card.profile.role ? (
                  <span className="inline-flex items-center gap-1">
                    <ShieldCheck className="size-3.5 text-muted" /> {card.profile.role}, {card.profile.two_factor ? '2FA on' : 'no 2FA yet'}
                  </span>
                ) : (
                  'no role'
                )}
              </Fact>
              <Fact label="Account id">
                <span className="font-mono text-xs" title={card.profile.id}>
                  {card.profile.id}
                </span>
              </Fact>
            </div>
            <div className="mt-5 border-t border-line pt-4">
              <UserActions card={card} canMoney={canMoney} onChanged={reload} />
            </div>
          </Card>

          <section className="mt-8">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <SectionLabel>Activity</SectionLabel>
              <Segmented
                size="sm"
                options={[
                  { value: '30d', label: 'Last 30 days' },
                  { value: 'all', label: 'All time' },
                ]}
                value={period}
                onChange={setPeriod}
              />
            </div>
            <StatsGrid stats={period === '30d' ? card.last_30_days : card.all_time} />
          </section>

          <div className="mt-4 grid items-start gap-4 xl:grid-cols-[2fr_1fr]">
            <SpendChart days={card.spend_days} />
            <FavoriteModels models={card.favorite_models} />
          </div>

          <div className="mt-4 grid items-start gap-4 xl:grid-cols-[2fr_1fr]">
            <TokensPanel userId={card.profile.id} tokens={card.tokens} onChanged={reload} />
            <ReactionsPanel userId={card.profile.id} reactions={card.reactions} onChanged={reload} />
          </div>

          <div className="mt-4 grid gap-4">
            <DebatesPanel userId={card.profile.id} version={version} />
            {canMoney && <LedgerPanel userId={card.profile.id} version={version} />}
            <AuditPanel targetId={card.profile.id} targetType="user" entries={card.audit} aside="last 50: about the account, and by it as an admin" />
          </div>
        </div>
      )}
    </Page>
  );
};

export default AdminUser;
