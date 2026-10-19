import { useEffect, useState } from 'react';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { getVoices } from '../api/media';

/**
 * `valid` — ElevenLabs accepted the key; `invalid` — it was rejected; `unknown` — the check
 * itself failed (network, rate limit), so the key gets the benefit of the doubt.
 */
export type TtsKeyStatus = 'none' | 'checking' | 'valid' | 'invalid' | 'unknown';

export interface TtsKeyCheck {
  status: TtsKeyStatus;
  /** Why the key was rejected (or the check failed). */
  error: string | null;
  /** Whether the key's plan is a paid one (the Music API of rap battles needs it); null: unknown. */
  paidPlan: boolean | null;
}

interface Checked extends TtsKeyCheck {
  key: string;
}

/** Lists the voices with the key (the API calls ElevenLabs with it and caches the list). */
export const checkElevenLabsKey = (key: string): Promise<TtsKeyCheck> =>
  getVoices('elevenlabs', { language: 'English', participants: 0 }, key)
    .then((res): TtsKeyCheck => ({ status: 'valid', error: null, paidPlan: res.paid_plan ?? null }))
    .catch((err: unknown): TtsKeyCheck => {
      const status = getErrorStatus(err);
      // 502 = ElevenLabs answered with an error; other 4xx are ours, except rate limits.
      const rejected = status === 502 || (status !== null && status >= 400 && status < 500 && status !== 429);
      return { status: rejected ? 'invalid' : 'unknown', error: getErrorMessage(err), paidPlan: null };
    });

/**
 * Checks the user's own ElevenLabs key. Only a working key unlocks premium voices without
 * credits; while the check runs (or cannot run) the key counts as usable — see `ttsKeyUsable`.
 * `delayMs` debounces keys typed into a field.
 */
export const useElevenLabsKeyStatus = (key: string, delayMs = 0): TtsKeyCheck => {
  const [checked, setChecked] = useState<Checked | null>(null);

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void checkElevenLabsKey(key).then((result) => {
        if (!cancelled) setChecked({ key, ...result });
      });
    }, delayMs);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [key, delayMs]);

  if (!key) return { status: 'none', error: null, paidPlan: null };
  return checked?.key === key ? { status: checked.status, error: checked.error, paidPlan: checked.paidPlan } : { status: 'checking', error: null, paidPlan: null };
};

/** A key is set and ElevenLabs has not rejected it. `music`: the key also makes a rap battle's
 *  track, which a free plan cannot (an unknown plan gets the benefit of the doubt, as above). */
export const ttsKeyUsable = (check: TtsKeyCheck, music = false) => check.status !== 'none' && check.status !== 'invalid' && !(music && check.paidPlan === false);
