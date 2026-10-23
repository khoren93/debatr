/** What the site says when a sign-in with Google does not go through (pure; a .ts file for
 *  react-refresh). The server sends `/login?error=google_<code>` or, when connecting Google to an
 *  account, `/account?tab=security&google=<code>` (backend routes_google). */

const SIGN_IN: Record<string, string> = {
  google_cancelled: 'Google sign-in was cancelled.',
  google_expired: 'The Google sign-in took too long or started in another browser. Try again.',
  google_failed: 'Google sign-in did not work. Try again in a moment.',
  google_unverified: 'Google has not confirmed the email of that account. Use another one, or sign up with email.',
  google_disabled: 'This account is disabled.',
  google_exists:
    'An account with this email already exists. Sign in with its password (or reset it), then connect Google in Account → Security.',
  google_closed: 'Sign-ups are closed for now. Accounts that exist can still sign in.',
  google_off: 'Sign-in with Google is not available right now.',
};

/** The message for `?error=` of the sign-in pages, or null when it is not about Google. */
export const googleSignInError = (code: string | null): string | null => (code ? (SIGN_IN[code] ?? null) : null);

const CONNECT: Record<string, { ok: boolean; text: string }> = {
  linked: { ok: true, text: 'Google connected: you can sign in with it now.' },
  taken: { ok: false, text: 'That Google account is already connected to another account here.' },
  one_google: { ok: false, text: 'Disconnect the Google account you have before connecting another.' },
  expired: { ok: false, text: 'Connecting Google took too long. Try again.' },
  cancelled: { ok: false, text: 'Connecting Google was cancelled.' },
  failed: { ok: false, text: 'Connecting Google did not work. Try again in a moment.' },
};

/** The outcome of connecting Google (`?google=` on Account → Security). */
export const googleConnectResult = (code: string | null) => (code ? (CONNECT[code] ?? null) : null);
