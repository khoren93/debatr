import { SITE_CARD } from '../lib/og';
import { ogRoute } from '../server/og/render.server';
import type { Route } from './+types/og.site';

/** `/og/site.png`: the link preview picture of the home, gallery and ranking pages. */
export async function loader({ request }: Route.LoaderArgs) {
  return ogRoute(request, async () => SITE_CARD);
}
