import { useEffect, useState } from 'react';
import { getBillingConfig } from '../api/billing';
import type { BillingConfig } from '../api/types';

const FALLBACK: BillingConfig = {
  topup_amounts: [5, 10, 25],
  currency: 'usd',
  payments_mode: 'disabled',
  signup_bonus_usd: 0,
  tts_price_per_1k_chars: 0.15,
  tts_price_per_min: 0.15,
  music_price_per_min: 0.3,
  debate_usd: 0,
  voiced_debate_usd: 0,
  elevenlabs_available: false,
  elevenlabs_error: null,
};

let cached: BillingConfig | null = null;

/** Public billing configuration (cached for the session). */
export const useBillingConfig = () => {
  const [config, setConfig] = useState<BillingConfig>(cached ?? FALLBACK);
  const [loaded, setLoaded] = useState(cached !== null);

  useEffect(() => {
    if (cached) return;
    let cancelled = false;
    getBillingConfig()
      .then((c) => {
        cached = c;
        if (!cancelled) setConfig(c);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { config, loaded };
};
