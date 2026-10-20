import { useEffect, useState } from 'react';
import { searchTopicArchive } from '../api/topics';
import type { FormatId, TrendingTopic } from '../api/types';

const DEBOUNCE_MS = 300;
/** The archive answers searches of at least this many characters (backend `q`). */
export const MIN_ARCHIVE_QUERY = 2;

/**
 * Topics of earlier batches that match a search of the wizard's topic list (the list itself is
 * the newest batch). Debounced; while the next answer is on its way the last one of the same
 * list stays, so the caller filters it by the current words instead of flashing it away. A failed
 * search finds nothing: the archive is a bonus.
 */
export const useTopicArchive = (list: FormatId, query: string) => {
  const q = query.trim();
  const active = q.length >= MIN_ARCHIVE_QUERY;
  const [result, setResult] = useState<{ list: FormatId; q: string; topics: TrendingTopic[] } | null>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      searchTopicArchive(list, q)
        .then((res) => {
          if (!cancelled) setResult({ list, q, topics: res.topics });
        })
        .catch(() => {
          if (!cancelled) setResult({ list, q, topics: [] });
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [list, q, active]);

  const same = active && result?.list === list;
  return { topics: same ? result.topics : [], loading: active && !(same && result.q === q) };
};
