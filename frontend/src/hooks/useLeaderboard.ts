import { useEffect, useState } from 'react';
import { getErrorMessage } from '../api/client';
import { getLeaderboard } from '../api/gallery';
import type { Leaderboard } from '../api/types';

const TTL_MS = 60_000;
let cached: { at: number; request: Promise<Leaderboard> } | null = null;

/** Shared, briefly cached request so the wizard and the ranking page do not refetch it. */
const loadLeaderboard = (force: boolean) => {
  if (force || !cached || Date.now() - cached.at > TTL_MS) {
    const request = getLeaderboard();
    cached = { at: Date.now(), request };
    request.catch(() => {
      cached = null;
    });
  }
  return cached.request;
};

/** Model leaderboard built from audience votes on public debates. */
export const useLeaderboard = (enabled = true) => {
  const [data, setData] = useState<Leaderboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    loadLeaderboard(attempt > 0)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, attempt]);

  return { data, error, loading: enabled && data === null && error === null, retry: () => setAttempt((n) => n + 1) };
};
