import { data, isRouteErrorResponse } from 'react-router';
import { api, apiFailure } from './client';

export { toQuery } from './client';

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

/** The route error data of a failed API call: its status (a network failure counts as 503). */
export const routeError = (err: unknown) => {
  const response = apiFailure(err)?.response;
  const answered = response ? response.status : 503;
  const status = answered >= 500 ? 503 : answered;
  const detail = (response?.data as { detail?: unknown } | undefined)?.detail;
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
