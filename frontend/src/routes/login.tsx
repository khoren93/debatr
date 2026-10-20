import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import Login from '../pages/Login';

export default function LoginRoute() {
  return (
    <>
      <Seo {...privateSeo('Sign in')} />
      <Login />
    </>
  );
}
