import { useEffect, useState } from 'react';
import { getErrorMessage } from '../api/client';
import { getTrendingTopics } from '../api/topics';
import type { FormatId, TrendingTopics } from '../api/types';

const TTL_MS = 5 * 60_000;
const cache = new Map<FormatId, { at: number; request: Promise<TrendingTopics> }>();

/** Shared, cached request per list: the topics change once per batch (daily in production). */
const loadTrendingTopics = (list: FormatId, force: boolean) => {
  const hit = cache.get(list);
  if (!force && hit && Date.now() - hit.at <= TTL_MS) return hit.request;
  const request = getTrendingTopics(list);
  cache.set(list, { at: Date.now(), request });
  request.catch(() => {
    if (cache.get(list)?.request === request) cache.delete(list);
  });
  return request;
};

/** Topics made from today's news for a list (`FormatSpec.topicList`). */
export const useTrendingTopics = (list: FormatId, enabled = true) => {
  const [state, setState] = useState<{ list: FormatId; data: TrendingTopics | null; error: string | null } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    loadTrendingTopics(list, attempt > 0)
      .then((data) => {
        if (!cancelled) setState({ list, data, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ list, data: null, error: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [list, enabled, attempt]);

  // Another list's answer is not this one's: loading until the new list arrives.
  const current = state?.list === list ? state : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: enabled && current === null,
    retry: () => setAttempt((n) => n + 1),
  };
};
