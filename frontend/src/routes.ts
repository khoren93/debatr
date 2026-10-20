import { index, layout, route, type RouteConfig } from '@react-router/dev/routes';

/**
 * Route tree. `_site` = the app shell (session + site status from the server). Public pages
 * render on the server (loader for the first document, clientLoader straight to the API on
 * navigations); `_client` pages render only in the browser (HydrateFallback on the server);
 * `_private` ones also need a session. The admin console is a separate SPA (admin.html). Every
 * page renders one `<Seo>` (components/Seo.tsx): the document has no title of its own.
 */
export default [
  layout('routes/_site.tsx', [
    index('routes/home.tsx'),
    route('gallery', 'routes/gallery.tsx'),
    route('leaderboard', 'routes/leaderboard.tsx'),
    // Canonical addresses end in the topic's words (backend services/seo): /d/{slug}/{kebab}.
    route('d/:slug/:kebab?', 'routes/debate.tsx'),
    route('t/:slug/:kebab?', 'routes/topic.tsx'),
    layout('routes/_client.tsx', [
      route('login', 'routes/login.tsx'),
      route('register', 'routes/register.tsx'),
      route('debate/:id', 'routes/debate-owner.tsx'),
      layout('routes/_private.tsx', [
        route('library', 'routes/library.tsx'),
        route('create', 'routes/create.tsx'),
        route('account', 'routes/account.tsx'),
        route('device', 'routes/device.tsx'),
      ]),
    ]),
    route('*', 'routes/not-found.tsx'),
  ]),
  // Link preview pictures (lib/og.ts, src/server/og): `{slug}.png` of a debate or a topic.
  route('og/d/:file', 'routes/og.debate.ts'),
  route('og/t/:file', 'routes/og.topic.ts'),
  route('og/site.png', 'routes/og.site.ts'),
  route('healthz', 'routes/healthz.ts'),
] satisfies RouteConfig;
