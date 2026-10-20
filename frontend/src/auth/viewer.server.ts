import type { User } from '../api/types';
import { serverApi } from '../api/server.server';
import type { Viewer } from './viewer';

/** `Sec-Fetch-Site` values whose navigations carry SameSite=Strict cookies. */
const FIRST_PARTY = new Set(['same-origin', 'same-site', 'none']);

/** A navigation that would have brought the session cookie (not a link from another site). */
export const firstParty = (request: Request) => FIRST_PARTY.has(request.headers.get('sec-fetch-site') ?? '');

/** The session behind a document request (see `Viewer`). */
export async function readViewer(request: Request): Promise<Viewer> {
  if (!request.headers.has('cookie')) return { user: null, known: firstParty(request) };
  try {
    return { user: await serverApi<User | null>(request, '/auth/me'), known: true };
  } catch (err) {
    if (request.signal.aborted) throw err;
    // The API is in trouble: render anonymously and let the browser ask again.
    return { user: null, known: false };
  }
}
