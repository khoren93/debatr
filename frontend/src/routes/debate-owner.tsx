import { redirect } from 'react-router';
import { getErrorStatus } from '../api/client';
import { getDebate } from '../api/debates';
import { routeError } from '../api/route';
import { Seo } from '../components/Seo';
import { DebateError } from '../components/debate/DebateError';
import { privateSeo } from '../lib/seo';
import DebateView from '../pages/DebateView';
import type { Route } from './+types/debate-owner';

/** `/debate/:id`: the owner's view of any debate (drafts, private, live); browser only. */
export async function clientLoader({ params, request }: Route.ClientLoaderArgs) {
  try {
    return { debate: await getDebate(params.id) };
  } catch (err) {
    if (getErrorStatus(err) === 401) {
      const url = new URL(request.url);
      throw redirect(`/login?next=${encodeURIComponent(url.pathname + url.search)}`);
    }
    throw routeError(err);
  }
}

export default function DebateOwnerRoute({ loaderData, params }: Route.ComponentProps) {
  const { debate } = loaderData;
  return (
    <>
      <Seo {...privateSeo(debate.settings.topic || debate.title || 'Debate')} />
      <DebateView key={params.id} initial={debate} id={params.id} />
    </>
  );
}

export function ErrorBoundary() {
  return <DebateError backTo="/library" />;
}
