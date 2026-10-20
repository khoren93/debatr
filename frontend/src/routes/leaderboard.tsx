import { routeGet, toQuery, type ApiGet } from '../api/route';
import { serverGet } from '../api/server.server';
import type { FormatId, Leaderboard as Ranking } from '../api/types';
import { RouteError } from '../components/RouteError';
import { Seo } from '../components/Seo';
import { leaderboardSeo } from '../lib/seo';
import Leaderboard from '../pages/Leaderboard';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/leaderboard';

async function load(get: ApiGet, request: Request) {
  const format: FormatId = new URL(request.url).searchParams.get('format') === 'rap_battle' ? 'rap_battle' : 'debate';
  return { format, data: await get<Ranking>(`/gallery/leaderboard${toQuery({ format })}`) };
}

export const middleware: Route.MiddlewareFunction[] = [microcache];
export const loader = ({ request }: Route.LoaderArgs) => load(serverGet(request), request);
export const clientLoader = ({ request }: Route.ClientLoaderArgs) => load(routeGet, request);

export default function LeaderboardRoute({ loaderData }: Route.ComponentProps) {
  return (
    <>
      <Seo {...leaderboardSeo(loaderData.format)} />
      <Leaderboard format={loaderData.format} data={loaderData.data} />
    </>
  );
}

export function ErrorBoundary() {
  return <RouteError what="the ranking" />;
}
