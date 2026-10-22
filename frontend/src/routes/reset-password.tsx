import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import ResetPassword from '../pages/ResetPassword';

export default function ResetPasswordRoute() {
  return (
    <>
      <Seo {...privateSeo('Reset password')} />
      <ResetPassword />
    </>
  );
}
