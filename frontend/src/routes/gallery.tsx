import { routeGet, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { GalleryResponse } from '../api/types';
import { RouteError } from '../components/RouteError';
import { galleryFilters, galleryPath } from '../lib/gallery';
import Gallery from '../pages/Gallery';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/gallery';

async function load(get: ApiGet, request: Request) {
  const filters = galleryFilters(new URL(request.url).searchParams);
  const { items } = await get<GalleryResponse>(galleryPath(filters));
  return { filters, items };
}

export const middleware: Route.MiddlewareFunction[] = [microcache];
export const loader = ({ request }: Route.LoaderArgs) => load(serverGet(request), request);
export const clientLoader = ({ request }: Route.ClientLoaderArgs) => load(routeGet, request);

export default function GalleryRoute({ loaderData }: Route.ComponentProps) {
  return <Gallery filters={loaderData.filters} items={loaderData.items} />;
}

export function ErrorBoundary() {
  return <RouteError what="the gallery" />;
}
