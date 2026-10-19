import { useEffect, useState } from 'react';
import { suggestMotions } from '../api/motions';
import type { MotionSuggestions } from '../api/types';

/** Shorter texts match too much to be worth asking about. */
const MIN_LENGTH = 8;

/**
 * The topic the wizard's text would join and similar topics (debounced). `fresh` is false while
 * a changed text is being looked up: the previous similar topics stay on screen meanwhile, but a
 * "joins this topic" line must only describe the text as it is now.
 */
export const useMotionSuggestions = (topic: string, language: string, remixOf: string | undefined) => {
  const [loaded, setLoaded] = useState<{ key: string; data: MotionSuggestions } | null>(null);
  const query = topic.trim();
  const enabled = query.length >= MIN_LENGTH;
  const key = `${query}\n${language}\n${remixOf ?? ''}`;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      suggestMotions({ topic: query, language, remix_of: remixOf })
        .then((data) => {
          if (!cancelled) setLoaded({ key, data });
        })
        .catch(() => {
          // Suggestions are a hint: without them the wizard works the same.
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [enabled, query, language, remixOf, key]);

  if (!enabled || !loaded) return { data: null, fresh: false };
  return { data: loaded.data, fresh: loaded.key === key };
};
