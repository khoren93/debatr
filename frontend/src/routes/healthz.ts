/** Health check of the SSR server (Docker HEALTHCHECK): answers without touching the API. */
export const loader = () => new Response('ok', { headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' } });
