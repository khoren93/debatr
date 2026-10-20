import { useSyncExternalStore } from 'react';

const subscribe = () => () => {};

/**
 * False while a page renders on the server and during its hydration, true from then on (and on
 * every render that starts in the browser). What differs between the server and the viewer — the
 * time zone, the current moment, `window`, browser storage — waits for it, so the first client
 * render matches the server's HTML and React keeps it instead of rendering the page again.
 */
export const useHydrated = (): boolean => useSyncExternalStore(subscribe, () => true, () => false);
