import { Outlet } from 'react-router';
import { Seo } from '../components/Seo';
import { Page } from '../components/layout/AppShell';
import { PageLoader } from '../components/ui';
import { privateSeo } from '../lib/seo';
import type { Route } from './+types/_client';

/** Pages that render only in the browser (sign-in, the wizard, the account…): the server sends
 *  the shell with this loader, the browser takes over after hydration. None of them belongs in
 *  a search index (also said in the header, for crawlers that never run the page). */

export const middleware: Route.MiddlewareFunction[] = [
  async (_args, next) => {
    const response = await next();
    response.headers.set('X-Robots-Tag', 'noindex, nofollow');
    return response;
  },
];

export function clientLoader() {
  return null;
}

export function HydrateFallback() {
  return (
    <Page>
      <Seo {...privateSeo('')} />
      <PageLoader />
    </Page>
  );
}

export default function ClientPages() {
  return <Outlet />;
}
