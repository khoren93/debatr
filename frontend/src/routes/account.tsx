import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import Account from '../pages/Account';

export default function AccountRoute() {
  return (
    <>
      <Seo {...privateSeo('Account')} />
      <Account />
    </>
  );
}
