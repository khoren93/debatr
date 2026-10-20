import { isRouteErrorResponse, useRevalidator, useRouteError } from 'react-router';
import type { ReactNode } from 'react';
import { UNAVAILABLE, routeErrorOf } from '../api/route';
import { Page } from './layout/AppShell';
import { Button, EmptyState, ErrorBox, LinkButton } from './ui';

interface Missing {
  title: string;
  text?: string;
  icon?: ReactNode;
  action?: ReactNode;
}

interface Props {
  /** What this page says for 404 / 410 (default: the generic 404 page). */
  missing?: Missing;
  /** "the gallery": "Could not load the gallery: …". */
  what?: string;
  /** A page's own state for a status (the debate page's "private"), or null for the default. */
  render?: (status: number, detail: string) => ReactNode | null;
}

/** The generic 404 page of the design: mono kicker, big title, the way home. */
export const NotFoundPage = () => (
  <Page className="text-center">
    <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">404</div>
    <h1 className="mt-2 font-display text-4xl font-extrabold tracking-tight">Page not found</h1>
    <p className="mt-3 text-muted">The page you are looking for does not exist.</p>
    <div className="mt-6">
      <LinkButton to="/" variant="secondary">
        Back home
      </LinkButton>
    </div>
  </Page>
);

/** ErrorBoundary body of a page route: the same on the server (with the status code) and after
 *  a client navigation. */
export const RouteError = ({ missing, what = 'this page', render }: Props) => {
  const error = useRouteError();
  const revalidator = useRevalidator();
  const { status, detail } = routeErrorOf(error);
  const custom = render?.(status, detail);
  if (custom) return custom;
  if (status === 404 || status === 410) {
    if (!missing) return <NotFoundPage />;
    return (
      <Page>
        <EmptyState className="mt-6" icon={missing.icon} title={missing.title} text={missing.text} action={missing.action ?? <LinkButton to="/">Back home</LinkButton>} />
      </Page>
    );
  }
  if (status >= 500 && !isRouteErrorResponse(error)) console.error(error);
  return (
    <Page>
      <div className="mt-6 flex flex-col items-start gap-3">
        <ErrorBox className="w-full">
          Could not load {what}: {status === 503 ? UNAVAILABLE : detail || 'something went wrong.'}
        </ErrorBox>
        <Button variant="secondary" loading={revalidator.state === 'loading'} onClick={() => void revalidator.revalidate()}>
          Try again
        </Button>
      </div>
    </Page>
  );
};
