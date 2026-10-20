import { data } from 'react-router';
import { UNAVAILABLE, type ApiErrorData, type ApiGet } from './route';

/**
 * The SSR server's FastAPI client, for route loaders. The `.server` suffix keeps it out of the
 * browser bundle (React Router's build refuses such an import in client code); in the browser
 * pages keep calling the API through `client.ts`.
 *
 * Requests go to API_INTERNAL_URL over the internal network (natively http://localhost:8000,
 * compose sets http://api:8000) and carry the visitor's identity, so the API answers exactly as it
 * would answer the browser: the session cookie (owner buttons, likes, votes), the client IP (rate
 * limits, view counts; uvicorn trusts the proxy headers), the user agent and the language. The
 * cookie is never logged, and the API's `Set-Cookie` stays here: the browser refreshes its session
 * on its own requests, and a page that set cookies could not be cached.
 */

const FORWARDED_HEADERS = ['cookie', 'x-forwarded-for', 'user-agent', 'accept-language'] as const;

/** Past it the page is answered with 503 instead of hanging on a stuck API. */
export const API_TIMEOUT_MS = 3000;

/** Seconds a browser or crawler should wait after a 503. */
const RETRY_AFTER_S = 30;

/** compose sets http://api:8000; `npm run dev` against the Docker stack reuses VITE_DEV_API_TARGET. */
export const apiInternalUrl = (): string => (process.env.API_INTERNAL_URL || process.env.VITE_DEV_API_TARGET || 'http://localhost:8000').replace(/\/+$/, '');

/** The headers of the visitor's request that go along to the API, marked as the renderer's
 *  (backend views.RENDER_HEADER: its loads count no views, the page's beacon does). `anonymous`:
 *  without the cookie, for what must look the same to everyone (link preview pictures). */
export const forwardedHeaders = (request: Request, { anonymous = false }: { anonymous?: boolean } = {}): Headers => {
  const headers = new Headers({ accept: 'application/json', 'x-debatr-render': 'server' });
  for (const name of FORWARDED_HEADERS) {
    if (anonymous && name === 'cookie') continue;
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
};

const unavailable = () => data<ApiErrorData>({ status: 503, detail: UNAVAILABLE }, { status: 503, headers: { 'Retry-After': String(RETRY_AFTER_S) } });

const detailOf = async (response: Response): Promise<string> => {
  try {
    const body: unknown = await response.json();
    const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : undefined;
    return typeof detail === 'string' ? detail : response.statusText;
  } catch {
    return response.statusText;
  }
};

/**
 * GET `/api{path}` as the visitor and return the JSON body. A 4xx answer is thrown as route error
 * data with the same status (404 → "not found", 403 → private, 401 → sign in), a 5xx, a timeout or
 * an unreachable API as a 503 with Retry-After. A request the visitor abandoned rethrows its abort.
 */
export async function serverApi<T>(request: Request, path: string, { timeoutMs = API_TIMEOUT_MS, anonymous = false }: { timeoutMs?: number; anonymous?: boolean } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiInternalUrl()}/api${path}`, {
      headers: forwardedHeaders(request, { anonymous }),
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(timeoutMs)]),
    });
  } catch (err) {
    if (request.signal.aborted) throw err;
    console.warn(`[api] GET ${path}: ${err instanceof Error ? err.name : 'failed'}`);
    throw unavailable();
  }
  if (response.ok) return (await response.json()) as T;
  if (response.status >= 400 && response.status < 500) {
    throw data<ApiErrorData>({ status: response.status, detail: await detailOf(response) }, { status: response.status });
  }
  console.warn(`[api] GET ${path}: ${response.status}`);
  await response.body?.cancel();
  throw unavailable();
}

/** `serverApi` bound to the visitor's request: the `ApiGet` of server loaders. */
export const serverGet =
  (request: Request): ApiGet =>
  <T>(path: string) =>
    serverApi<T>(request, path);
