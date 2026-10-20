import { Outlet } from 'react-router';
import type { SiteStatus } from '../api/types';
import { AuthProvider } from '../auth/AuthContext';
import { viewerContext, type Viewer } from '../auth/viewer';
import { readViewer } from '../auth/viewer.server';
import { RouteError } from '../components/RouteError';
import { AppShell } from '../components/layout/AppShell';
import { SiteStatusProvider } from '../hooks/useSiteStatus';
import { serverSiteStatus } from '../server/siteStatus.server';
import type { Route } from './+types/_site';

/** The app shell of every page: the session and the site levers come with the document, so the
 *  sidebar shows the account (and a maintenance banner) in the server's HTML. */

export const middleware: Route.MiddlewareFunction[] = [
  async ({ request, context }, next) => {
    context.set(viewerContext, await readViewer(request));
    const response = await next();
    // Pages differ by session: no shared cache may hand one visitor's page to another.
    response.headers.append('Vary', 'Cookie');
    if (!response.headers.has('Cache-Control')) response.headers.set('Cache-Control', request.headers.has('cookie') ? 'private, no-cache' : 'no-cache');
    return response;
  },
];

export async function loader({ request, context }: Route.LoaderArgs) {
  return { viewer: context.get(viewerContext), status: await serverSiteStatus(request) };
}

/** Only when the shell was not server-rendered: the browser asks for the session itself. */
export function clientLoader(): { viewer: Viewer; status: SiteStatus | null } {
  return { viewer: { user: null, known: false }, status: null };
}

// The session lives in AuthProvider from here on (sign-in, sign-out, refresh).
export const shouldRevalidate = () => false;

export default function Site({ loaderData }: Route.ComponentProps) {
  return (
    <AuthProvider viewer={loaderData.viewer}>
      <SiteStatusProvider value={loaderData.status}>
        <AppShell>
          <Outlet />
        </AppShell>
      </SiteStatusProvider>
    </AuthProvider>
  );
}

export function ErrorBoundary() {
  return <RouteError />;
}
