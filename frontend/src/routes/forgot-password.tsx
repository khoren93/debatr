import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import ForgotPassword from '../pages/ForgotPassword';

export default function ForgotPasswordRoute() {
  return (
    <>
      <Seo {...privateSeo('Forgot password')} />
      <ForgotPassword />
    </>
  );
}
