import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import Device from '../pages/Device';

export default function DeviceRoute() {
  return (
    <>
      <Seo {...privateSeo('Approve a sign-in')} />
      <Device />
    </>
  );
}
