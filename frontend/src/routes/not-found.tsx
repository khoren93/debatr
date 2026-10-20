import { data } from 'react-router';
import { RouteError } from '../components/RouteError';

/** Any other address: a real 404 (not the app with a 200). */
const missing = (): never => {
  throw data(null, { status: 404 });
};

export const loader = missing;
export const clientLoader = missing;

export default function NotFound() {
  return null;
}

export function ErrorBoundary() {
  return <RouteError />;
}
