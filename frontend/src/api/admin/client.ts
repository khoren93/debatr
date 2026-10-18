import axios, { isAxiosError } from 'axios';

/**
 * The admin console's own client: `/api/admin` on the console's origin, the session's CSRF token
 * on every unsafe request, and one place that hears about an ended session (the console then
 * shows its sign-in page). Never shares state with the site's client in `../client.ts`.
 */
export const adminApi = axios.create({
  baseURL: '/api/admin',
  timeout: 30_000,
  withCredentials: true,
});

let csrfToken: string | null = null;
let onSignedOut: (() => void) | null = null;

export const setCsrfToken = (token: string | null) => {
  csrfToken = token;
};

export const setSignedOutHandler = (handler: (() => void) | null) => {
  onSignedOut = handler;
};

const SAFE_METHODS = new Set(['get', 'head', 'options']);
// Sign-in steps answer 401 for an expired ticket, which is not an ended session.
const SIGN_IN_STEPS = ['/auth/login', '/auth/totp', '/auth/enroll/'];

adminApi.interceptors.request.use((config) => {
  if (csrfToken && !SAFE_METHODS.has((config.method ?? 'get').toLowerCase())) {
    config.headers.set('X-CSRF-Token', csrfToken);
  }
  return config;
});

adminApi.interceptors.response.use(
  (response) => response,
  (error) => {
    // A 401 from anything but the sign-in steps means the session ended (idle, revoked, …).
    const url = isAxiosError(error) ? (error.config?.url ?? '') : '';
    const signingIn = SIGN_IN_STEPS.some((step) => url.startsWith(step));
    if (isAxiosError(error) && error.response?.status === 401 && !signingIn) {
      csrfToken = null;
      onSignedOut?.();
    }
    return Promise.reject(error);
  },
);

/** The 403 a fresh authenticator code would lift (the console asks for one and retries). */
export const needsSudo = (error: unknown): boolean =>
  isAxiosError(error) && error.response?.status === 403 && error.response.headers['x-admin-sudo'] === 'required';
