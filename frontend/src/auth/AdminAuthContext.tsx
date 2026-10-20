import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router';
import { adminLogout, getAdminMe } from '../api/admin/auth';
import { setCsrfToken, setSignedOutHandler } from '../api/admin/client';
import type { AdminMe } from '../api/admin/types';
import { PageLoader } from '../components/ui';

interface AdminAuthState {
  me: AdminMe | null;
  /** True until the first /admin/auth/me round-trip finished. */
  loading: boolean;
  /** After signing in, or with fresh session data (sudo, regenerated codes). */
  setMe: (me: AdminMe | null) => void;
  refresh: () => Promise<AdminMe | null>;
  signOut: () => Promise<void>;
}

const AdminAuthContext = createContext<AdminAuthState | null>(null);

/** The admin console's session (separate from the site's AuthProvider and its cookie). */
export const AdminAuthProvider = ({ children }: { children: ReactNode }) => {
  const [me, setMeState] = useState<AdminMe | null>(null);
  const [loading, setLoading] = useState(true);

  const setMe = useCallback((value: AdminMe | null) => {
    setCsrfToken(value?.csrf ?? null);
    setMeState(value);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const value = await getAdminMe();
      setMe(value);
      return value;
    } catch {
      setMe(null);
      return null;
    }
  }, [setMe]);

  // Initial probe of the session cookie (setState only inside the promise callbacks).
  useEffect(() => {
    let cancelled = false;
    getAdminMe()
      .then((value) => {
        if (!cancelled) setMe(value);
      })
      .catch(() => {
        if (!cancelled) setMe(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [setMe]);

  // Any request that finds the session ended (idle, revoked, role taken away) signs out here.
  useEffect(() => {
    setSignedOutHandler(() => setMe(null));
    return () => setSignedOutHandler(null);
  }, [setMe]);

  const signOut = useCallback(async () => {
    try {
      await adminLogout();
    } finally {
      setMe(null);
    }
  }, [setMe]);

  const value = useMemo<AdminAuthState>(() => ({ me, loading, setMe, refresh, signOut }), [me, loading, setMe, refresh, signOut]);
  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>;
};

// eslint-disable-next-line react-refresh/only-export-components
export const useAdminAuth = (): AdminAuthState => {
  const ctx = useContext(AdminAuthContext);
  if (!ctx) throw new Error('useAdminAuth must be used within AdminAuthProvider');
  return ctx;
};

/** Sends visitors without a console session to the console's sign-in page. */
export const RequireAdmin = ({ children }: { children: ReactNode }) => {
  const { me, loading } = useAdminAuth();
  const location = useLocation();
  if (loading) return <PageLoader />;
  if (!me) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/admin/login?next=${next}`} replace />;
  }
  return <>{children}</>;
};
