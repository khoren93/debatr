import { createContext } from 'react-router';
import type { User } from '../api/types';

/**
 * Who the server rendered a page for. `known` means the answer is final: the request carried
 * cookies, or came from this site (or a typed address), so the session cookie would have come
 * along. A link from another site arrives without it (SameSite=Strict): that visit renders
 * anonymously and the browser asks `/auth/me` itself after hydration.
 */
export interface Viewer {
  user: User | null;
  known: boolean;
}

/** Set by the `_site` route's server middleware, read by its loader and `_private`. */
export const viewerContext = createContext<Viewer>({ user: null, known: false });
