/** The site's public origin for canonical links and link previews: SITE_URL (compose passes the
 *  API's value to `web`), else the address the request came to (`npm run dev`). */
export const siteOrigin = (request: Request): string => (process.env.SITE_URL || new URL(request.url).origin).replace(/\/+$/, '');
