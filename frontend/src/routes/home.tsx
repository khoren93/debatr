import { routeGet, toQuery, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { GalleryItem, GalleryResponse } from '../api/types';
import { RouteError } from '../components/RouteError';
import Landing from '../pages/Landing';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/home';

/** Debates in the "Trending in the gallery" row. */
const FEATURED = 3;

/** The landing is the first impression: debates with premium voices come first, the general
 *  trending list fills the free places; one card per topic in both lists (a topic in both shows
 *  its premium version). The row is optional: without the gallery it stays hidden. */
async function load(get: ApiGet): Promise<{ featured: GalleryItem[] }> {
  const list = (premium: boolean) => get<GalleryResponse>(`/gallery${toQuery({ limit: FEATURED, sort: 'trending', group: 'motion', premium_voices: premium || undefined })}`);
  try {
    const [premium, all] = await Promise.all([list(true), list(false)]);
    const topicOf = (item: GalleryItem) => item.motion?.slug ?? item.id;
    const topics = new Set(premium.items.map(topicOf));
    return { featured: [...premium.items, ...all.items.filter((item) => !topics.has(topicOf(item)))].slice(0, FEATURED) };
  } catch {
    return { featured: [] };
  }
}

export const middleware: Route.MiddlewareFunction[] = [microcache];
export const loader = ({ request }: Route.LoaderArgs) => load(serverGet(request));
export const clientLoader = () => load(routeGet);

export default function Home({ loaderData }: Route.ComponentProps) {
  return <Landing featured={loaderData.featured} />;
}

export function ErrorBoundary() {
  return <RouteError />;
}
