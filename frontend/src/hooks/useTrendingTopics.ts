import { useEffect, useState } from 'react';
import { getErrorMessage } from '../api/client';
import { getTrendingTopics } from '../api/topics';
import type { TrendingTopics } from '../api/types';

const TTL_MS = 5 * 60_000;
let cached: { at: number; request: Promise<TrendingTopics> } | null = null;

/** Shared, cached request: the topics change once per batch (daily in production). */
const loadTrendingTopics = (force: boolean) => {
  if (force || !cached || Date.now() - cached.at > TTL_MS) {
    const request = getTrendingTopics();
    cached = { at: Date.now(), request };
    request.catch(() => {
      cached = null;
    });
  }
  return cached.request;
};

/** Debate topics made from today's news. */
export const useTrendingTopics = (enabled = true) => {
  const [data, setData] = useState<TrendingTopics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    loadTrendingTopics(attempt > 0)
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
