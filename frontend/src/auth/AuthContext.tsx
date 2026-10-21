import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { getMe, logout as apiLogout } from '../api/auth';
import type { User } from '../api/types';
import type { Viewer } from './viewer';
import { track } from '../lib/presence';

interface AuthState {
  user: User | null;
  /** True until the first /auth/me round-trip finished. */
  loading: boolean;
  /** Re-fetch the profile (e.g. after a top-up or a charge). */
  refresh: () => Promise<User | null>;
  /** Set the user after login/register or profile edits. */
  setUser: (user: User | null) => void;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/** `viewer`: what the server rendered the page for (the `_site` loader). When it is not final
 *  (a visit from another site, see Viewer) the browser asks `/auth/me` after hydration. */
export const AuthProvider = ({ children, viewer }: { children: ReactNode; viewer?: Viewer }) => {
  const known = viewer?.known ?? false;
  const [user, setUser] = useState<User | null>(viewer?.user ?? null);
  const [loading, setLoading] = useState(!known);

  const refresh = useCallback(async () => {
    try {
      const me = await getMe();
      setUser(me);
      return me;
    } catch {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  // Probe of the session cookie when the server could not tell (setState only inside the promise callbacks).
  useEffect(() => {
    if (known) return;
    let cancelled = false;
    getMe()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [known]);

  const signOut = useCallback(async () => {
    track('logout');
    try {
      await apiLogout();
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthState>(() => ({ user, loading, refresh, setUser, signOut }), [user, loading, refresh, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = (): AuthState => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};
