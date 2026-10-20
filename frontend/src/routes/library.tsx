import { Seo } from '../components/Seo';
import { privateSeo } from '../lib/seo';
import Library from '../pages/Library';

export default function LibraryRoute() {
  return (
    <>
      <Seo {...privateSeo('Library')} />
      <Library />
    </>
  );
}
