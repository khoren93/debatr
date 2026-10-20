/**
 * The site's API client: `fetch` with the shape the API modules were written against (axios':
 * `api.get<T>(path, { params })` resolves to `{ data }`, a failure throws `ApiError` with
 * `response.status` / `response.data`), a few hundred bytes instead of axios' 19 KB on every page.
 * The admin console keeps its own axios client (api/admin/client.ts); the error helpers below read
 * both.
 */

/** Query parameters: an object of scalar values (string, number, boolean, null, undefined). */
type Params = object;
type ParamValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  params?: Params;
  headers?: Record<string, string>;
  /** `text`: the body as a string (CSV); by default JSON (a body that is not JSON stays text). */
  responseType?: 'json' | 'text';
  /** Milliseconds until the request gives up (no answer, like a lost connection). */
  timeout?: number;
  /** '' for paths outside /api's prefix (timeline.json under /api/media/files). */
  baseURL?: string;
}

export interface ApiResponse<T> {
  data: T;
  status: number;
  headers: Headers;
}

/** The API answered with an error status (`response`), or did not answer at all (null). */
export class ApiError extends Error {
  readonly response: { status: number; data: unknown; headers: Headers } | null;

  constructor(message: string, response: ApiError['response']) {
    super(message);
    this.name = 'ApiError';
    this.response = response;
  }
}

// In production (Caddy) and in `vite dev` (proxy) the API lives under /api.
export const API_BASE: string = import.meta.env.VITE_API_URL || '/api';
const TIMEOUT_MS = 90_000;

/** `?a=1&b=x` from the defined values (undefined and null are left out, false and 0 stay). */
export const toQuery = (params: Params): string => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params) as [string, ParamValue][]) if (value !== undefined && value !== null) search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : '';
};

const parse = (text: string): unknown => {
  if (!text) return '';
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
};

const request = async <T>(method: string, path: string, body: unknown, options: RequestOptions = {}): Promise<ApiResponse<T>> => {
  const { params, responseType = 'json', timeout = TIMEOUT_MS, baseURL = API_BASE } = options;
  const headers: Record<string, string> = { Accept: 'application/json, text/plain, */*', ...options.headers };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  let text: string;
  try {
    // The login is a same-site session cookie (credentials also when VITE_API_URL is elsewhere).
    response = await fetch(`${baseURL}${path}${params ? toQuery(params) : ''}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'include',
      signal: AbortSignal.timeout(timeout),
    });
    text = await response.text();
  } catch (err) {
    throw new ApiError(err instanceof Error ? err.message : 'Network error', null);
  }
  const data = responseType === 'text' ? text : parse(text);
  if (!response.ok) throw new ApiError(`Request failed with status code ${response.status}`, { status: response.status, data, headers: response.headers });
  return { data: data as T, status: response.status, headers: response.headers };
};

export const api = {
  get: <T = unknown>(path: string, options?: RequestOptions) => request<T>('GET', path, undefined, options),
  delete: <T = unknown>(path: string, options?: RequestOptions) => request<T>('DELETE', path, undefined, options),
  post: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) => request<T>('POST', path, body, options),
  put: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PUT', path, body, options),
  patch: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PATCH', path, body, options),
};

/** A failed API call of this client or of the console's axios one (both carry `response`, absent
 *  or null when nothing answered); null for any other error. */
export const apiFailure = (err: unknown): { response?: { status: number; data?: unknown } | null } | null =>
  err instanceof ApiError || (typeof err === 'object' && err !== null && (err as { isAxiosError?: unknown }).isAxiosError === true) ? (err as { response?: { status: number; data?: unknown } | null }) : null;

/** HTTP status of an API error, if any. */
export function getErrorStatus(err: unknown): number | null {
  return apiFailure(err)?.response?.status ?? null;
}

/** Extract a human-readable message from an API/network error. */
export function getErrorMessage(err: unknown): string {
  const failure = apiFailure(err);
  if (failure) {
    const detail = (failure.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (first && typeof first.msg === 'string') return first.msg.replace(/^Value error, /, '');
    }
    if (failure.response) return `Request failed (${failure.response.status})`;
    return 'Network error: could not reach the server';
  }
  if (err instanceof Error) return err.message;
  return 'Unknown error';
}
