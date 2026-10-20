import { serverApi } from '../api/server.server';
import type { MotionPage } from '../api/types';
import { topicCard } from '../lib/og';
import { ogRoute } from '../server/og/render.server';
import type { Route } from './+types/og.topic';

/** `/og/t/{slug}.png`: the link preview picture of a topic page (lib/og.ts topicOgImage). */
export async function loader({ request, params }: Route.LoaderArgs) {
  const slug = params.file.endsWith('.png') ? params.file.slice(0, -4) : '';
  if (!slug) return new Response(null, { status: 404 });
  return ogRoute(request, async () => topicCard(await serverApi<MotionPage>(request, `/motions/${encodeURIComponent(slug)}`, { anonymous: true })));
}
