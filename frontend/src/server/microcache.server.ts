import { LRUCache } from 'lru-cache';
import type { MiddlewareFunction } from 'react-router';
import { firstParty } from '../auth/viewer.server';

/**
 * Micro-cache of public pages for visitors without cookies (crawlers, link previews, first
 * visits): the same URL is rendered at most once per 30 s per process. Requests with cookies go
 * straight through (their pages are personal), and only complete 200 HTML answers without
 * Set-Cookie are kept. Whether the visit's session is known (`Viewer.known`) is part of the key:
 * the page tells the browser whether to ask `/auth/me` itself.
 */

interface Entry {
  status: number;
  headers: [string, string][];
  body: Uint8Array;
}

const cache = new LRUCache<string, Entry>({
  max: 200,
  ttl: 30_000,
  maxSize: 32 * 1024 * 1024,
  sizeCalculation: (entry) => Math.max(1, entry.body.byteLength),
});

export const microcache: MiddlewareFunction<Response> = async ({ request }, next) => {
  if (request.method !== 'GET' || request.headers.has('cookie')) return next();
  const url = new URL(request.url);
  const key = `${firstParty(request) ? 'known' : 'unknown'} ${url.pathname}${url.search}`;
  const hit = cache.get(key);
  if (hit) {
    const headers = new Headers(hit.headers);
    headers.set('X-Cache', 'HIT');
    return new Response(hit.body.slice(), { status: hit.status, headers });
  }
  const response = await next();
  const html = response.headers.get('content-type')?.startsWith('text/html');
  if (response.status === 200 && html && !response.headers.has('set-cookie') && response.body) {
    // Kept once the stream is complete; the visitor reads it as it renders.
    const copy = response.clone();
    copy
      .arrayBuffer()
      .then((buffer) => cache.set(key, { status: copy.status, headers: [...copy.headers], body: new Uint8Array(buffer) }))
      .catch(() => undefined);
    response.headers.set('X-Cache', 'MISS');
  }
  return response;
};
