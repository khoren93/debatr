import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

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
        .then((html) => {
          res.setHeader('Content-Type', 'text/html; charset=utf-8');
          res.setHeader('Cache-Control', 'no-cache');
          res.end(html);
        })
        .catch(next);
    });
  },
});

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), consolePage()],
  server: {
    port: 5173,
    // Local dev: proxy API (incl. SSE) to the backend so no CORS setup is needed.
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
