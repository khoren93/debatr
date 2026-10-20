import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

/** The admin console's build: admin.html → build/admin, served as /srv/admin by frontend/Caddyfile
 *  (ADMIN_HOST, or /admin on the site's origin without it). Its chunks live in admin-assets/ so
 *  they never collide with the site's /assets/. `npm run dev` serves the console from vite.config.ts. */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'build/admin',
    emptyOutDir: true,
    assetsDir: 'admin-assets',
    rollupOptions: { input: 'admin.html' },
  },
});
