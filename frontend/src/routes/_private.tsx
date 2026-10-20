import { Outlet, redirect } from 'react-router';
import { RequireAuth } from '../auth/RequireAuth';
import { viewerContext } from '../auth/viewer';
import type { Route } from './+types/_private';

/** Pages that need a session. A document request the server knows to be anonymous goes to the
 *  sign-in page at once; otherwise RequireAuth decides in the browser (also on navigations). */

export const middleware: Route.MiddlewareFunction[] = [
  ({ request, context }) => {
    const viewer = context.get(viewerContext);
    if (viewer.known && !viewer.user) {
      const url = new URL(request.url);
      throw redirect(`/login?next=${encodeURIComponent(url.pathname + url.search)}`);
    }
  },
];

export default function PrivatePages() {
  return (
    <RequireAuth>
      <Outlet />
    </RequireAuth>
  );
}
