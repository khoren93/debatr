import { useEffect, useState } from 'react';
import { getErrorMessage } from '../api/client';
import { estimateDebate } from '../api/debates';
import type { DebateConfig, Estimate } from '../api/types';

/**
 * Cost / length estimate of a wizard config (debounced). `ready` is false while the config is
 * incomplete (model list still loading); `credits` refreshes the estimate after a top-up.
 */
export const useEstimate = (config: DebateConfig, ready: boolean, credits: number) => {
  const [loaded, setLoaded] = useState<{ key: string; estimate: Estimate } | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  const configKey = JSON.stringify(config);
  const key = `${configKey}#${credits}#${attempt}`;

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      estimateDebate(JSON.parse(configKey) as DebateConfig)
        .then((estimate) => {
          if (!cancelled) setLoaded({ key, estimate });
        })
        .catch((err: unknown) => {
          if (!cancelled) setFailed({ key, message: getErrorMessage(err) });
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [ready, configKey, key]);

  const estimate = loaded?.key === key ? loaded.estimate : null;
  const error = failed?.key === key ? failed.message : null;
  // The last result stays on screen while a changed config is re-estimated.
  const shown = estimate ?? (error ? null : (loaded?.estimate ?? null));
  return {
    estimate,
    /** Current estimate, or the previous one while the new one loads. */
    shown,
    error,
    estimating: ready && !estimate && !error,
    retry: () => setAttempt((n) => n + 1),
  };
};

/** What the run costs in credits (or in provider money with own keys). */
export const estimateCost = (estimate: Estimate) => estimate.credits_cost_usd || estimate.llm_cost_usd + estimate.tts_cost_usd;
