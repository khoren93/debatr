import { EyeOff, Lock } from 'lucide-react';
import { useLocation } from 'react-router';
import { useAuth } from '../../auth/AuthContext';
import { Page } from '../layout/AppShell';
import { RouteError } from '../RouteError';
import { EmptyState, LinkButton } from '../ui';

/** ErrorBoundary of the debate routes: private (403), not found (404), unpublished (410) or
 *  failed to load. */
export const DebateError = ({ backTo }: { backTo: string }) => {
  const { user } = useAuth();
  const location = useLocation();
  const next = encodeURIComponent(location.pathname + location.search);
  return (
    <RouteError
      what="the debate"
      missing={{ title: 'Debate not found', text: 'It may have been deleted or unpublished.', action: <LinkButton to={backTo} variant="secondary">Back</LinkButton> }}
      render={(status) =>
        status === 410 ? (
          <Page>
            <EmptyState icon={<EyeOff className="size-5" />} title="This debate was unpublished" text="Its author took it out of the gallery." action={<LinkButton to={backTo} variant="secondary">Back</LinkButton>} />
          </Page>
        ) : status === 403 ? (
          <Page>
            <EmptyState
              icon={<Lock className="size-5" />}
              title="This debate is private"
              text={user ? 'Only its owner can open it.' : 'Sign in if it is yours.'}
              action={!user ? <LinkButton to={`/login?next=${next}`}>Sign in</LinkButton> : <LinkButton to="/library" variant="secondary">Your library</LinkButton>}
            />
          </Page>
        ) : null
      }
    />
  );
};
