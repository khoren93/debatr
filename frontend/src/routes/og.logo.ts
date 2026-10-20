import { logoReference } from '../server/og/render.server';
import type { Route } from './+types/og.logo';

/** `/og/logo.png?model={id}`: a model's logo as a reference picture for the AI covers (the
 *  worker fetches it; backend services/media/cover_logos). `X-Logo` names the logo; 404 for a
 *  model without one. */
export async function loader({ request }: Route.LoaderArgs) {
  const model = new URL(request.url).searchParams.get('model')?.slice(0, 200) ?? '';
  const logo = model ? await logoReference(model) : null;
  if (!logo) return new Response(null, { status: 404, headers: { 'Cache-Control': 'public, max-age=3600' } });
  return new Response(logo.body as Uint8Array<ArrayBuffer>, {
    headers: { 'Content-Type': 'image/png', 'X-Logo': logo.name, 'Cache-Control': 'public, max-age=86400' },
  });
}
