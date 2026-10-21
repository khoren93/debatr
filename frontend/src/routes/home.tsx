import { routeGet, toQuery, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { GalleryItem, GalleryResponse } from '../api/types';
import { RouteError } from '../components/RouteError';
import { Seo } from '../components/Seo';
import { homeSeo } from '../lib/seo';
import Landing from '../pages/Landing';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/home';

/** Debates in the "Trending in the gallery" row. */
const FEATURED = 3;
/** Trending topics looked at: the hero's and the row's, with room for debates without audio. */
const POOL = 8;

/** The landing is the first impression, in English. The hero plays the most popular debate (the
 *  first trending topic with its video ready); in the row below, debates with premium voices come
 *  first and the general trending list fills the free places, one card per topic and none of the
 *  hero's. Both are optional: without the gallery the hero is the static poster and the row
 *  stays hidden. */
async function load(get: ApiGet): Promise<{ hero: GalleryItem | null; featured: GalleryItem[] }> {
  const list = (premium: boolean) => get<GalleryResponse>(`/gallery${toQuery({ limit: POOL, sort: 'trending', group: 'motion', language: 'en', premium_voices: premium || undefined })}`);
  try {
    const [premium, all] = await Promise.all([list(true), list(false)]);
    const topicOf = (item: GalleryItem) => item.motion?.slug ?? item.id;
    const hero = all.items.find((item) => item.has_media) ?? premium.items.find((item) => item.has_media) ?? null;
    const taken = new Set(hero ? [topicOf(hero)] : []);
    const featured: GalleryItem[] = [];
    for (const item of [...premium.items, ...all.items]) {
      if (featured.length === FEATURED) break;
      if (taken.has(topicOf(item))) continue;
      taken.add(topicOf(item));
      featured.push(item);
    }
    return { hero, featured };
  } catch {
    return { hero: null, featured: [] };
  }
}

export const middleware: Route.MiddlewareFunction[] = [microcache];
export const loader = ({ request }: Route.LoaderArgs) => load(serverGet(request));
export const clientLoader = () => load(routeGet);

export default function Home({ loaderData }: Route.ComponentProps) {
  return (
    <>
      <Seo {...homeSeo()} />
      <Landing hero={loaderData.hero} featured={loaderData.featured} />
    </>
  );
}

export function ErrorBoundary() {
  return <RouteError />;
}
