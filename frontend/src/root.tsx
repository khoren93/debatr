import type { ReactNode } from 'react';
import { Links, Meta, Outlet, Scripts, ScrollRestoration, useMatches, useRouteError } from 'react-router';
import { routeErrorOf } from './api/route';
import { Seo } from './components/Seo';
import { ToastProvider } from './components/ui';
import { PRELOAD_FONTS } from './fonts';
import { errorSeo, type PageHandle } from './lib/seo';
import type { Route } from './+types/root';
import './index.css';

/** The page's language for `<html lang>`: the deepest route that knows it (`handle.lang`). */
const usePageLang = (): string => {
  const matches = useMatches();
  for (let i = matches.length - 1; i >= 0; i--) {
    const { handle, loaderData } = matches[i];
    const lang = loaderData !== undefined ? (handle as PageHandle | undefined)?.lang?.(loaderData) : undefined;
    if (lang) return lang;
  }
  return 'en';
};

/** The fonts (src/fonts.ts, bundled into the root stylesheet) start with the stylesheet, not after it. */
export const links: Route.LinksFunction = () => PRELOAD_FONTS.map((href) => ({ rel: 'preload', href, as: 'font', type: 'font/woff2', crossOrigin: 'anonymous' }));

/** The HTML document of every page (the server renders it; the browser hydrates it). Titles and
 *  the rest of the head come from each page's `<Seo>`. */
export function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang={usePageLang()}>
      <head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <meta name="theme-color" content="#0A0B0F" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Outlet />
    </ToastProvider>
  );
}

/** Last resort, when even the app shell failed: a bare page with the status. */
export function ErrorBoundary() {
  const { status, detail } = routeErrorOf(useRouteError());
  return (
    <main className="grid min-h-screen place-items-center bg-ink px-6 text-center text-text">
      <Seo {...errorSeo(status)} />
      <div>
        <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">{status}</div>
        <h1 className="mt-2 font-display text-3xl font-extrabold tracking-tight">{status === 404 ? 'Page not found' : 'Something went wrong'}</h1>
        {detail && status !== 404 && <p className="mt-3 text-muted">{detail}</p>}
        <a href="/" className="mt-6 inline-block text-sm text-accent hover:text-accent-hover">
          Back home
        </a>
      </div>
    </main>
  );
}
