import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { reactRouter } from '@react-router/dev/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, type Plugin } from 'vite';

/** React Router's Fast Refresh preamble: its plugin adds refresh code to every module of src/,
 *  the console's included, and the site's pages load this in <Scripts />. */
const REFRESH_PREAMBLE = '<script type="module" src="/@id/__x00__virtual:react-router/inject-hmr-runtime"></script>';

/** `npm run dev`: the admin console is its own SPA (admin.html, built by vite.admin.config.ts);
 *  page loads under /admin get its document, so it runs on this port like it does on the site's
 *  origin without ADMIN_HOST. */
const consolePage = (): Plugin => ({
  name: 'debatr:console-page',
  apply: 'serve',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      const url = req.url ?? '/';
      const page = req.method === 'GET' && /^\/admin(\/|\?|$)/.test(url) && (req.headers.accept ?? '').includes('text/html');
      if (!page) return next();
      readFile(resolve(server.config.root, 'admin.html'), 'utf8')
        .then((html) => server.transformIndexHtml(url, html))
        .then((html) => html.replace('<script type="module" src="/src/admin-main.tsx">', `${REFRESH_PREAMBLE}\n    <script type="module" src="/src/admin-main.tsx">`))
        .then((html) => {
          res.setHeader('Content-Type', 'text/html; charset=utf-8');
          res.setHeader('Cache-Control', 'no-cache');
          res.end(html);
        })
        .catch(next);
    });
  },
});

// https://vite.dev/config/ — the console's page goes before React Router's server rendering.
export default defineConfig({
  plugins: [tailwindcss(), consolePage(), reactRouter()],
  server: {
    port: 5173,
    // Local dev: proxy API (incl. SSE) to the backend so no CORS setup is needed.
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
      // robots.txt and the sitemaps come from the API, as behind Caddy.
      '^/(robots\\.txt|sitemap\\.xml|sitemaps/.*)$': {
        target: process.env.VITE_DEV_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
