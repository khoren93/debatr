import { useEffect, useRef, useState } from 'react';
import { getErrorMessage } from '../../api/client';

/**
 * Loads `load` (a module-level function, so it stays the same between renders), again on
 * `reload()` (`reload(true)` asks the server to skip its caches) and every `pollMs` while the
 * tab is visible. The last data stays on screen while the next load runs (`loading`).
 */
export function useLoad<T>(load: (refresh: boolean) => Promise<T>, pollMs = 0) {
  const [state, setState] = useState<{ version: number; data: T } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const fresh = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const refresh = fresh.current;
    fresh.current = false;
    load(refresh)
      .then((data) => {
        if (!cancelled) {
          setState({ version, data });
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [load, version]);

  useEffect(() => {
    if (!pollMs) return;
    const id = window.setInterval(() => {
      if (!document.hidden) setVersion((n) => n + 1);
    }, pollMs);
    return () => window.clearInterval(id);
  }, [pollMs]);

  const reload = (refresh = false) => {
    fresh.current = refresh;
    setVersion((n) => n + 1);
  };
  return { data: state?.data ?? null, loading: state?.version !== version, error, reload };
}
