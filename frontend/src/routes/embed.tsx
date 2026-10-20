import { ArrowUpRight } from 'lucide-react';
import { useRouteError } from 'react-router';
import { routeErrorOf, routeGet, type ApiGet } from '../api/route';
import { serverApi } from '../api/server.server';
import type { DebateDetail } from '../api/types';
import { Seo } from '../components/Seo';
import { LogoMark } from '../components/ui';
import { APP_NAME } from '../lib/brand';
import { embedDebate, embedTitle, parseEmbedQuery } from '../lib/embed';
import { embedSeo, errorSeo, type PageHandle } from '../lib/seo';
import Embed, { EmbedWindow } from '../pages/Embed';
import { sharedMicrocache } from '../server/microcache.server';
import type { Route } from './+types/embed';

/**
 * `/embed/:slug` (`?format=short`, `?t=` seconds): a public debate's player for other sites'
 * iframes (lib/embed.ts; oEmbed hands out the same address). Outside the app shell: no session,
 * no sidebar. In a third-party frame the SameSite=Strict session never arrives, so the page is
 * always rendered anonymously (the API is asked without the cookie) and is the same for everyone.
 */
async function load(get: ApiGet, request: Request, slug: string) {
  const debate = await get<DebateDetail>(`/gallery/${encodeURIComponent(slug)}`);
  // Only what the player needs: the page's data is part of its HTML.
  return { debate: embedDebate(debate), options: parseEmbedQuery(new URL(request.url).searchParams) };
}

/** Any page may frame it (the rest of the site: only itself, frontend/Caddyfile): no
 *  `frame-ancestors` at all, since `*` still refuses parents without a network scheme — editors'
 *  `srcdoc` previews (WordPress shows oEmbed players in one), desktop apps (`app://`), local files.
 *  No index wants it (the debate's page is the one to find); shared caches may keep it a while. */
const embedHeaders: Route.MiddlewareFunction = async (_args, next) => {
  const response = await next();
  response.headers.delete('X-Frame-Options');
  response.headers.delete('Content-Security-Policy');
  response.headers.set('X-Robots-Tag', 'noindex');
  const status = response.status;
  if (!response.headers.has('Cache-Control')) response.headers.set('Cache-Control', status === 200 ? 'public, max-age=300' : status < 500 ? 'public, max-age=60' : 'no-store');
  return response;
};

export const middleware: Route.MiddlewareFunction[] = [embedHeaders, sharedMicrocache];

export const loader = ({ request, params }: Route.LoaderArgs) => load((path) => serverApi(request, path, { anonymous: true }), request, params.slug);
export const clientLoader = ({ request, params }: Route.ClientLoaderArgs) => load(routeGet, request, params.slug);

export const handle: PageHandle<Route.ComponentProps['loaderData']> = { lang: (data) => data.debate.language, framed: true };

export default function EmbedRoute({ loaderData }: Route.ComponentProps) {
  const { debate, options } = loaderData;
  return (
    <>
      <Seo {...embedSeo(embedTitle(debate.topic, debate.participants))} />
      <Embed key={`${debate.slug}-${options.format}-${options.start}`} debate={debate} options={options} />
    </>
  );
}

/** Not public (any more), unknown or the service is down: a card in the frame, with the status. */
export function ErrorBoundary() {
  const { status } = routeErrorOf(useRouteError());
  const gone = status === 404 || status === 410 || status === 403;
  return (
    <EmbedWindow>
      <Seo {...errorSeo(status)} />
      <div className="grid max-w-sm justify-items-center gap-3 p-6 text-center">
        <LogoMark size={40} />
        <div className="font-display text-lg font-bold tracking-tight">{gone ? 'This debate is not available' : `${APP_NAME} is unavailable right now`}</div>
        <p className="text-sm text-muted">{gone ? 'It is private or was taken down by its author.' : 'Try again in a minute.'}</p>
        <a href="/gallery?ref=embed" target="_blank" rel="noopener" className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent hover:text-accent-hover">
          More debates on {APP_NAME} <ArrowUpRight className="size-4" />
        </a>
      </div>
    </EmbedWindow>
  );
}
