import { Layers } from 'lucide-react';
import { redirect } from 'react-router';
import { routeGet, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { MotionPage } from '../api/types';
import { RouteError } from '../components/RouteError';
import { Seo } from '../components/Seo';
import { LinkButton } from '../components/ui';
import { canonicalRedirect, topicSeo, type PageHandle } from '../lib/seo';
import Topic from '../pages/Topic';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/topic';

/** `/t/:slug/:kebab?`: a topic. A merged topic answers with the one it went into; that, an old
 *  title's kebab or none at all redirect (301) to the canonical `path`. */
async function load(get: ApiGet, request: Request, slug: string) {
  const page = await get<MotionPage>(`/motions/${encodeURIComponent(slug)}`);
  const target = canonicalRedirect(new URL(request.url), page.path || `/t/${page.slug}`);
  if (target) throw redirect(target, 301);
  return { page };
}

export const middleware: Route.MiddlewareFunction[] = [microcache];
export const loader = ({ request, params }: Route.LoaderArgs) => load(serverGet(request), request, params.slug);
export const clientLoader = ({ request, params }: Route.ClientLoaderArgs) => load(routeGet, request, params.slug);

export const handle: PageHandle<Route.ComponentProps['loaderData']> = { lang: (data) => topicSeo(data.page).lang };

export default function TopicRoute({ loaderData }: Route.ComponentProps) {
  return (
    <>
      <Seo {...topicSeo(loaderData.page)} />
      <Topic page={loaderData.page} />
    </>
  );
}

export function ErrorBoundary() {
  return (
    <RouteError
      what="the topic"
      missing={{ icon: <Layers className="size-5" />, title: 'Nothing published on this topic', text: 'Its debates are private or were taken down.', action: <LinkButton to="/gallery">Browse the gallery</LinkButton> }}
    />
  );
}
