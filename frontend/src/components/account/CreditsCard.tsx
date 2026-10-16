import { useState } from 'react';
import { createCheckout } from '../../api/billing';
import { getErrorMessage } from '../../api/client';
import type { BillingConfig, User } from '../../api/types';
import { Button, Card, Hint, SectionLabel, useToast } from '../ui';
import { money, moneyShort } from './helpers';

/** Rough all-in cost of one debate at the default settings, for the "≈ N more debates" line. */
const DEBATE_COST_USD = 0.12;
const FALLBACK_AMOUNTS = [5, 10, 25];

interface CreditsCardProps {
  user: User;
  config: BillingConfig;
  configLoaded: boolean;
  /** Called after an instant (dev-mode) top-up so the page can refresh the balance. */
  onToppedUp: () => void;
}

export const CreditsCard = ({ user, config, configLoaded, onToppedUp }: CreditsCardProps) => {
  const toast = useToast();
  const [chosen, setChosen] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const amounts = config.topup_amounts.length > 0 ? config.topup_amounts : FALLBACK_AMOUNTS;
  const amount = chosen !== null && amounts.includes(chosen) ? chosen : amounts[Math.floor(amounts.length / 2)];
  const balance = user.credits_usd;
  const debatesLeft = Math.max(0, Math.floor(balance / DEBATE_COST_USD));
  const disabled = !configLoaded || config.payments_mode === 'disabled';

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

  const hint = !configLoaded
    ? ' '
    : config.payments_mode === 'disabled'
      ? 'Payments coming soon'
      : config.payments_mode === 'dev'
        ? 'Development mode: credited instantly'
        : 'Secure checkout by Stripe';

  return (
    <Card tone="accent" padding="lg">
      <SectionLabel>Credits</SectionLabel>
      <div className={`mt-2 font-display text-[clamp(40px,5vw,56px)] font-extrabold leading-none tracking-[-0.04em] ${balance < 0 ? 'text-con' : ''}`}>
        {money(balance)}
      </div>
      <div className="mt-1.5 text-[13px] text-muted">
        {balance > 0 ? `≈ ${debatesLeft} more debates at current settings` : 'Top up to run paid models'}
      </div>
      <div className="mt-[18px] flex flex-wrap gap-2" role="radiogroup" aria-label="Top-up amount">
        {amounts.map((a) => {
          const active = a === amount;
          return (
            <button
              key={a}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => setChosen(a)}
              disabled={disabled}
              className={`min-w-[70px] flex-1 cursor-pointer rounded-field border px-3 py-3 text-center text-sm font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                active ? 'border-accent bg-accent text-ink' : 'border-line-2 bg-surface-2 text-text-2 hover:border-line-3 hover:text-text'
              }`}
            >
              {moneyShort(a)}
            </button>
          );
        })}
      </div>
      <Button size="lg" className="mt-3 w-full" onClick={topUp} loading={busy} disabled={disabled}>
        Add {moneyShort(amount)} in credits
      </Button>
      <Hint className="text-center">{hint}</Hint>
    </Card>
  );
};
