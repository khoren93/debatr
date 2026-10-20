import { isAxiosError } from 'axios';
import { data, isRouteErrorResponse } from 'react-router';
import { api } from './client';

/**
 * Route data: one load function per page serves the server `loader` (with `serverGet`, the
 * visitor's cookie forwarded) and the browser `clientLoader` (with `routeGet`, straight to the API
 * as before). Both throw the same route error data, so a page's ErrorBoundary and status code do
 * not depend on where it was loaded.
 */

/** GET an API path (`/gallery?sort=new`, without the /api prefix) and return its JSON. */
export type ApiGet = <T>(path: string) => Promise<T>;

/** What a failed load throws (React Router route error data): the API's status and `detail`. */
export interface ApiErrorData {
  status: number;
  detail: string;
}

export const UNAVAILABLE = 'The service is unavailable right now. Try again in a minute.';

/** `?a=1&b=x` from the defined values (axios' param rules: undefined and null are left out). */
export const toQuery = (params: Record<string, string | number | boolean | null | undefined>): string => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null) search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : '';
};

/** The route error data of an axios failure: its status (a network failure counts as 503). */
export const routeError = (err: unknown) => {
  const answered = isAxiosError(err) && err.response ? err.response.status : 503;
  const status = answered >= 500 ? 503 : answered;
  const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
  return data<ApiErrorData>({ status, detail: status === 503 ? UNAVAILABLE : typeof detail === 'string' ? detail : 'Request failed' }, { status });
};

/** The browser's `ApiGet` for client loaders. */
export const routeGet: ApiGet = async <T>(path: string) => {
  try {
    return (await api.get<T>(path)).data;
  } catch (err) {
    throw routeError(err);
  }
};

/** Status and API detail of what a loader threw (an exception counts as 500). */
export const routeErrorOf = (error: unknown): { status: number; detail: string } => {
  if (isRouteErrorResponse(error)) {
    const body = error.data as Partial<ApiErrorData> | string | null;
    return { status: error.status, detail: (typeof body === 'object' && body?.detail) || (typeof body === 'string' ? body : '') || error.statusText };
  }
  return { status: 500, detail: error instanceof Error ? error.message : '' };
};
