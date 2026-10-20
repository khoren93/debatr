import { data } from 'react-router';
import { routeGet, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { GalleryResponse } from '../api/types';
import { RouteError } from '../components/RouteError';
import { Seo } from '../components/Seo';
import { galleryFilters, galleryPath } from '../lib/gallery';
import { gallerySeo } from '../lib/seo';
import Gallery from '../pages/Gallery';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/gallery';

async function load(get: ApiGet, request: Request) {
  const filters = galleryFilters(new URL(request.url).searchParams);
  const { items, total } = await get<GalleryResponse>(galleryPath(filters));
  // A page past the last one does not exist (an old link after debates were unpublished).
  if (filters.page > 1 && items.length === 0) throw data({ status: 404, detail: 'No such page' }, { status: 404 });
  return { filters, items, total };
}

export const middleware: Route.MiddlewareFunction[] = [microcache];
export const loader = ({ request }: Route.LoaderArgs) => load(serverGet(request), request);
export const clientLoader = ({ request }: Route.ClientLoaderArgs) => load(routeGet, request);

export default function GalleryRoute({ loaderData }: Route.ComponentProps) {
  return (
    <>
      <Seo {...gallerySeo(loaderData.filters)} />
      <Gallery filters={loaderData.filters} items={loaderData.items} total={loaderData.total} />
    </>
  );
}

export function ErrorBoundary() {
  return <RouteError what="the gallery" />;
}
