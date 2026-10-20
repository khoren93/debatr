import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import CreateDebate from '../pages/CreateDebate';

export default function CreateDebateRoute() {
  return (
    <>
      <Seo {...privateSeo('Create a debate')} />
      <CreateDebate />
    </>
  );
}
