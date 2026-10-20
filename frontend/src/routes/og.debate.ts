import { serverApi } from '../api/server.server';
import type { DebateDetail } from '../api/types';
import { debateCard } from '../lib/og';
import { ogRoute } from '../server/og/render.server';
import type { Route } from './+types/og.debate';

/** `/og/d/{slug}.png`: the link preview picture of a public debate (lib/og.ts debateOgImage). */
export async function loader({ request, params }: Route.LoaderArgs) {
  const slug = params.file.endsWith('.png') ? params.file.slice(0, -4) : '';
  if (!slug) return new Response(null, { status: 404 });
  return ogRoute(request, async () => debateCard(await serverApi<DebateDetail>(request, `/gallery/${encodeURIComponent(slug)}`, { anonymous: true })));
}
