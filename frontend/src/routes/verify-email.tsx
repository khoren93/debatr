import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import VerifyEmail from '../pages/VerifyEmail';

export default function VerifyEmailRoute() {
  return (
    <>
      <Seo {...privateSeo('Confirm email')} />
      <VerifyEmail />
    </>
  );
}
