import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { useSiteStatus } from '../hooks/useSiteStatus';
import { pageShown, setPresenceEnabled } from '../lib/presence';

/** Reports every page the router shows (lib/presence.ts); renders nothing. A changed query of
 *  the same page (the gallery's filters) is not a new page. */
export const Presence = () => {
  const { pathname } = useLocation();
  const on = useSiteStatus().analytics !== false;

  useEffect(() => {
    setPresenceEnabled(on);
    if (on) pageShown(pathname, window.location.search);
  }, [pathname, on]);

  return null;
};
