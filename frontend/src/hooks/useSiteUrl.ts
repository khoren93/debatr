import { useRouteLoaderData } from 'react-router';

/** The site's origin as the server rendered the page (the `_site` route's loader, from
 *  SITE_URL): the base of canonical links and link previews. */
export const useSiteUrl = (): string => {
  const site = useRouteLoaderData('routes/_site') as { siteUrl?: string } | undefined;
  return site?.siteUrl ?? '';
};
