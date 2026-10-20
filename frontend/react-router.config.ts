import type { Config } from '@react-router/dev/config';

/** Server rendering of the site (src/root.tsx, src/routes.ts); the admin console is a separate
 *  static build (vite.admin.config.ts). */
export default {
  appDirectory: 'src',
  ssr: true,
  // The whole (small) route manifest comes with the first page: navigations never ask the Node
  // server for routes, they go straight to the API through the client loaders.
  routeDiscovery: { mode: 'initial' },
} satisfies Config;
