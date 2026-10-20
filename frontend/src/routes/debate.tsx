import { redirect } from 'react-router';
import { routeGet, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { DebateDetail } from '../api/types';
import { viewerContext } from '../auth/viewer';
import { Seo } from '../components/Seo';
import { DebateError } from '../components/debate/DebateError';
import { canonicalRedirect, debateSeo, type PageHandle } from '../lib/seo';
import DebateView from '../pages/DebateView';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/debate';

/** `/d/:slug/:kebab?`: a public debate. Any other spelling than the API's canonical `path`
 *  (no kebab, an old one) answers 301; an unpublished debate 410 (the API's status). */
async function load(get: ApiGet, request: Request, slug: string) {
  const debate = await get<DebateDetail>(`/gallery/${encodeURIComponent(slug)}`);
  const target = debate.path ? canonicalRedirect(new URL(request.url), debate.path) : null;
  if (target) throw redirect(target, 301);
  return debate;
}

export const middleware: Route.MiddlewareFunction[] = [microcache];

/** `viewer`: whom the API personalised the copy for (the forwarded cookie's user, null = anonymous). */
export async function loader({ request, params, context }: Route.LoaderArgs) {
  return { debate: await load(serverGet(request), request, params.slug), viewer: context.get(viewerContext).user?.id ?? null };
}

export async function clientLoader({ request, params }: Route.ClientLoaderArgs) {
  return { debate: await load(routeGet, request, params.slug), viewer: undefined };
}

export const handle: PageHandle<Route.ComponentProps['loaderData']> = { lang: (data) => data.debate.settings.language_code };

export default function DebateRoute({ loaderData, params }: Route.ComponentProps) {
  return (
    <>
      <Seo {...debateSeo(loaderData.debate)} />
      <DebateView key={params.slug} initial={loaderData.debate} viewer={loaderData.viewer} slug={params.slug} />
    </>
  );
}

export function ErrorBoundary() {
  return <DebateError backTo="/gallery" />;
}
