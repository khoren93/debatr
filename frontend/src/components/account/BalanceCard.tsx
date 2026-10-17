import { useState } from 'react';
import { createCheckout } from '../../api/billing';
import { getErrorMessage } from '../../api/client';
import type { BillingConfig, Usage, User } from '../../api/types';
import { formatCost } from '../../lib/format';
import { useLocalKey } from '../../lib/localKeys';
import { Button, SectionLabel, useToast } from '../ui';
import { money, moneyShort } from './helpers';

/** Rough all-in cost of one debate at the default settings, for the "≈ N debates" lines. */
const DEBATE_COST_USD = 0.12;
const FALLBACK_AMOUNTS = [5, 10, 25];

/** "~85 debates": rounded to fives so the chips do not pretend to be exact. */
const debatesFor = (usd: number) => {
  const n = usd / DEBATE_COST_USD;
  return n >= 10 ? Math.round(n / 5) * 5 : Math.floor(n);
};

interface BalanceCardProps {
  user: User;
  config: BillingConfig;
  configLoaded: boolean;
  /** This month's usage for the stats row (null while loading). */
  usage: Usage | null;
  /** Called after an instant (dev-mode) top-up so the page can refresh the balance. */
  onToppedUp: () => void;
  /** Switch to the "API keys" tab. */
  onShowKeys: () => void;
}

const Status = ({ tone, children }: { tone: 'low' | 'negative'; children: string }) => {
  const color = tone === 'low' ? 'bg-host/12 text-host' : 'bg-con/12 text-con';
  const dot = tone === 'low' ? 'bg-host' : 'bg-con';
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${color}`}>
      <span className={`size-1.5 rounded-full ${dot} animate-pulse-dot`} />
      {children}
    </span>
  );
};

/** BALANCE + TOP UP panel with this month's money stats underneath. */
export const BalanceCard = ({ user, config, configLoaded, usage, onToppedUp, onShowKeys }: BalanceCardProps) => {
  const toast = useToast();
  const [chosen, setChosen] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const browserKey = useLocalKey('openrouter');

  const amounts = config.topup_amounts.length > 0 ? config.topup_amounts : FALLBACK_AMOUNTS;
  const amount = chosen !== null && amounts.includes(chosen) ? chosen : amounts[Math.floor(amounts.length / 2)];
  const balance = user.credits_usd;
  const ownKey = Boolean(browserKey || user.openrouter_key_masked);
  const paymentsOff = configLoaded && config.payments_mode === 'disabled';
  const disabled = !configLoaded || paymentsOff;

  const topUp = async () => {
    setBusy(true);
    try {
      const res = await createCheckout(amount);
      if (res.instant) {
        toast.success(`Added ${moneyShort(amount)} in credits`);
        onToppedUp();
        setBusy(false);
      } else {
        // Stripe Checkout; the button stays busy until the page unloads.
        window.location.assign(res.url);
      }
    } catch (err) {
      toast.error(getErrorMessage(err));
      setBusy(false);
    }
  };

  const status = balance < 0 ? (
    <Status tone="negative">Below zero</Status>
  ) : balance < DEBATE_COST_USD ? (
    <Status tone="low">Running low</Status>
  ) : null;

  const note =
    balance < 0
      ? 'A run cost a little more than its estimate. Top up before the next paid debate; free models still work.'
      : balance < DEBATE_COST_USD
        ? ownKey
          ? 'Your own OpenRouter key runs the models. Credits pay for premium voices and AI pictures.'
          : 'Not enough for another debate with paid models. Top up, or add your own keys to keep generating. Free models still work.'
        : `Enough for about ${debatesFor(balance)} more debates at the default settings.`;

  const hint = !configLoaded
    ? ' '
    : config.payments_mode === 'disabled'
      ? 'Card payments are coming soon.'
      : config.payments_mode === 'dev'
        ? 'Development mode: credited instantly.'
        : 'Secure checkout by Stripe.';

  const avg = usage && usage.debates > 0 ? usage.spent_usd / usage.debates : null;
  const stats = [
    { label: 'Spent this month', value: usage ? formatCost(usage.spent_usd) : '—', tone: 'text-text' },
    { label: 'Topped up', value: usage ? formatCost(usage.topped_up_usd) : '—', tone: 'text-ok' },
    { label: 'Debates', value: usage ? String(usage.debates) : '—', tone: 'text-text' },
    { label: 'Avg per debate', value: avg !== null ? formatCost(avg) : '—', tone: 'text-text' },
  ];

  return (
    <div className="@container overflow-hidden rounded-[24px] border border-line bg-surface bg-[radial-gradient(80%_140%_at_0%_0%,rgb(217_255_61/0.10),transparent_55%)]">
      <div className="grid @2xl:grid-cols-2">
        <div className="p-[clamp(22px,3vw,32px)]">
          <div className="flex min-h-[26px] items-center justify-between gap-2.5">
            <SectionLabel>Balance</SectionLabel>
            {status}
          </div>
          <div
            className={`mt-3.5 font-display text-[clamp(52px,7vw,80px)] leading-[0.9] font-extrabold tracking-[-0.045em] ${balance < 0 ? 'text-con' : ''}`}
          >
            {money(balance)}
          </div>
          <p className="mt-3 max-w-[340px] text-sm leading-normal text-pretty text-text-3">{note}</p>
          <button type="button" onClick={onShowKeys} className="mt-3.5 cursor-pointer text-[13px] text-accent hover:text-accent-hover">
            {ownKey ? 'Manage my own keys →' : 'Use my own keys →'}
          </button>
        </div>
        <div className="flex flex-col justify-center border-t border-line bg-ink/35 p-[clamp(22px,3vw,32px)] @2xl:border-t-0 @2xl:border-l">
          <SectionLabel>Top up</SectionLabel>
          <div className="mt-3.5 grid grid-cols-[repeat(auto-fit,minmax(80px,1fr))] gap-2" role="radiogroup" aria-label="Top-up amount">
            {amounts.map((a) => {
              const active = a === amount;
              return (
                <button
                  key={a}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setChosen(a)}
                  disabled={!configLoaded}
                  className={`cursor-pointer rounded-[14px] border px-1.5 py-3.5 text-center transition-colors disabled:cursor-wait ${
                    active ? 'border-accent bg-accent text-ink' : 'border-line bg-surface-2 text-text-2 enabled:hover:border-line-3'
                  }`}
                >
                  <div className="font-display text-xl font-bold tracking-[-0.02em]">{moneyShort(a)}</div>
                  <div className="mt-0.5 text-[11px] opacity-75">~{debatesFor(a)} debates</div>
                </button>
              );
            })}
          </div>
          {paymentsOff ? (
            <div
              aria-disabled="true"
              className="mt-3 flex cursor-not-allowed items-center justify-center gap-2.5 rounded-[14px] bg-surface-3 p-[15px] text-[15px] font-bold text-muted"
            >
              <span>Add {moneyShort(amount)} in credits</span>
              <span className="rounded-md bg-surface-4 px-2 py-[3px] font-mono text-[10px] font-medium tracking-[0.06em] text-text-3">SOON</span>
            </div>
          ) : (
            <Button size="lg" className="mt-3 w-full" onClick={topUp} loading={busy} disabled={disabled}>
              Add {moneyShort(amount)} in credits
            </Button>
          )}
          <div className="mt-2.5 text-center text-xs text-dim">{hint}</div>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-px border-t border-line bg-line @2xl:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="bg-surface px-[clamp(18px,3vw,32px)] py-4">
            <dt className="text-xs text-muted">{s.label}</dt>
            <dd className={`mt-1 font-mono text-base ${s.tone}`}>{s.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
};
