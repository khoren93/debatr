import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import Register from '../pages/Register';

export default function RegisterRoute() {
  return (
    <>
      <Seo {...privateSeo('Create an account')} />
      <Register />
    </>
  );
}
