import { routeGet, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { DebateDetail } from '../api/types';
import { viewerContext } from '../auth/viewer';
import { DebateError } from '../components/debate/DebateError';
import DebateView from '../pages/DebateView';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/debate';

/** `/d/:slug`: a public debate. */
const load = (get: ApiGet, slug: string) => get<DebateDetail>(`/gallery/${encodeURIComponent(slug)}`);

export const middleware: Route.MiddlewareFunction[] = [microcache];

/** `viewer`: whom the API personalised the copy for (the forwarded cookie's user, null = anonymous). */
export async function loader({ request, params, context }: Route.LoaderArgs) {
  return { debate: await load(serverGet(request), params.slug), viewer: context.get(viewerContext).user?.id ?? null };
}

export async function clientLoader({ params }: Route.ClientLoaderArgs) {
  return { debate: await load(routeGet, params.slug), viewer: undefined };
}

export default function DebateRoute({ loaderData, params }: Route.ComponentProps) {
  return <DebateView key={params.slug} initial={loaderData.debate} viewer={loaderData.viewer} slug={params.slug} />;
}

export function ErrorBoundary() {
  return <DebateError backTo="/gallery" />;
}
