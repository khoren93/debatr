import { Suspense, type ReactNode } from 'react';
import { useHydrated } from '../../hooks/useHydrated';

interface Props {
  /** A function, so nothing browser-only is even created while the server renders. */
  children: () => ReactNode;
  /** Server HTML, the first client render and the wait for a `lazy()` chunk. Give it the size of
   *  the content, so nothing jumps when the content arrives. */
  fallback?: ReactNode;
}

/**
 * Browser-only UI (Remotion players, the MP4 renderer, canvas work) after hydration, `fallback`
 * before. Such modules reach code that renders on the server only through `lazy()` inside this
 * (eslint.config.js: `no-restricted-imports`).
 */
export const ClientOnly = ({ children, fallback = null }: Props) => {
  const hydrated = useHydrated();
  return hydrated ? <Suspense fallback={fallback}>{children()}</Suspense> : fallback;
};
