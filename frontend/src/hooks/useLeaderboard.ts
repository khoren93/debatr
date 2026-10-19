import { useEffect, useState } from 'react';
import { getErrorMessage } from '../api/client';
import { getLeaderboard } from '../api/gallery';
import type { FormatId, Leaderboard } from '../api/types';

const TTL_MS = 60_000;
const cache = new Map<FormatId, { at: number; request: Promise<Leaderboard> }>();

/** Shared, briefly cached request per format so the wizard and the ranking page do not refetch it. */
const loadLeaderboard = (format: FormatId, force: boolean) => {
  const hit = cache.get(format);
  if (!force && hit && Date.now() - hit.at <= TTL_MS) return hit.request;
  const request = getLeaderboard(format);
  cache.set(format, { at: Date.now(), request });
  request.catch(() => {
    cache.delete(format);
  });
  return request;
};

/** Model leaderboard built from audience votes on public debates (or rap battles). */
export const useLeaderboard = (enabled = true, format: FormatId = 'debate') => {
  const [loaded, setLoaded] = useState<{ format: FormatId; data: Leaderboard } | null>(null);
  const [failed, setFailed] = useState<{ format: FormatId; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    loadLeaderboard(format, attempt > 0)
      .then((res) => {
        if (!cancelled) setLoaded({ format, data: res });
      })
      .catch((err: unknown) => {
        if (!cancelled) setFailed({ format, message: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, format, attempt]);

  // Results of another format (the tab was switched) never show under this one.
  const data = loaded?.format === format ? loaded.data : null;
  const error = failed?.format === format && !data ? failed.message : null;
  return { data, error, loading: enabled && data === null && error === null, retry: () => setAttempt((n) => n + 1) };
};
