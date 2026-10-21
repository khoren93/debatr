import { RouteError } from '../components/RouteError';
import { Seo } from '../components/Seo';
import { privacySeo } from '../lib/seo';
import Privacy from '../pages/Privacy';
import { microcache } from '../server/microcache.server';
import type { Route } from './+types/privacy';

export const middleware: Route.MiddlewareFunction[] = [microcache];

export default function PrivacyRoute() {
  return (
    <>
      <Seo {...privacySeo()} />
      <Privacy />
    </>
  );
}

export function ErrorBoundary() {
  return <RouteError />;
}
