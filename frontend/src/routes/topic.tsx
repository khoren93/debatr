import { Layers } from 'lucide-react';
import { redirect } from 'react-router';
import { routeGet, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { MotionPage } from '../api/types';
import { RouteError } from '../components/RouteError';
import { LinkButton } from '../components/ui';
import Topic from '../pages/Topic';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/topic';

async function load(get: ApiGet, slug: string) {
  const page = await get<MotionPage>(`/motions/${encodeURIComponent(slug)}`);
  // A topic merged into another one answers with that one: its own address.
  if (page.slug !== slug) throw redirect(`/t/${page.slug}`, 301);
  return { page };
}

export const middleware: Route.MiddlewareFunction[] = [microcache];
export const loader = ({ request, params }: Route.LoaderArgs) => load(serverGet(request), params.slug);
export const clientLoader = ({ params }: Route.ClientLoaderArgs) => load(routeGet, params.slug);

export default function TopicRoute({ loaderData }: Route.ComponentProps) {
  return <Topic page={loaderData.page} />;
}

export function ErrorBoundary() {
  return (
    <RouteError
      what="the topic"
      missing={{ icon: <Layers className="size-5" />, title: 'Nothing published on this topic', text: 'Its debates are private or were taken down.', action: <LinkButton to="/gallery">Browse the gallery</LinkButton> }}
    />
  );
}
