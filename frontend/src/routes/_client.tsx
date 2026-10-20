import { Outlet } from 'react-router';
import { Page } from '../components/layout/AppShell';
import { PageLoader } from '../components/ui';

/** Pages that render only in the browser (sign-in, the wizard, the account…): the server sends
 *  the shell with this loader, the browser takes over after hydration. */

export function clientLoader() {
  return null;
}

export function HydrateFallback() {
  return (
    <Page>
      <PageLoader />
    </Page>
  );
}

export default function ClientPages() {
  return <Outlet />;
}
