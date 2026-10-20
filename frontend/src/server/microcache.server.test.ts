import { describe, expect, it, vi } from 'vitest';
import { microcache, sharedMicrocache } from './microcache.server';

type Args = Parameters<typeof microcache>[0];

const page = (body: string, init: ResponseInit = {}) => new Response(body, { status: 200, ...init, headers: { 'content-type': 'text/html; charset=utf-8', ...(init.headers as Record<string, string>) } });
const run = async (url: string, headers: Record<string, string>, next: () => Promise<Response>) =>
  (await microcache({ request: new Request(url, { headers }) } as Args, next as Parameters<typeof microcache>[1])) as Response;
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('microcache', () => {
  it('serves a cookie-less page from memory the second time', async () => {
    const next = vi.fn(async () => page('<h1>hi</h1>'));
    const first = await run('http://site.test/a', { 'sec-fetch-site': 'none' }, next);
    expect(first.headers.get('x-cache')).toBe('MISS');
    expect(await first.text()).toBe('<h1>hi</h1>');
    await settle();
    const second = await run('http://site.test/a', { 'sec-fetch-site': 'none' }, next);
    expect(second.headers.get('x-cache')).toBe('HIT');
    expect(await second.text()).toBe('<h1>hi</h1>');
    expect(next).toHaveBeenCalledTimes(1);
  });

  it('keeps known and unknown sessions apart (the page tells the browser whether to ask)', async () => {
    const next = vi.fn(async () => page('x'));
    await (await run('http://site.test/b', { 'sec-fetch-site': 'none' }, next)).text();
    await settle();
    await run('http://site.test/b', { 'sec-fetch-site': 'cross-site' }, next);
    expect(next).toHaveBeenCalledTimes(2);
  });

  it('never caches personal pages, errors or answers that set cookies', async () => {
    const withCookie = vi.fn(async () => page('mine'));
    await run('http://site.test/c', { cookie: 'session=1' }, withCookie);
    await run('http://site.test/c', { cookie: 'session=1' }, withCookie);
    expect(withCookie).toHaveBeenCalledTimes(2);

    const missing = vi.fn(async () => page('nope', { status: 404 }));
    await (await run('http://site.test/d', {}, missing)).text();
    await settle();
    await run('http://site.test/d', {}, missing);
    expect(missing).toHaveBeenCalledTimes(2);

    const setsCookie = vi.fn(async () => page('x', { headers: { 'set-cookie': 'a=1' } }));
    await (await run('http://site.test/e', {}, setsCookie)).text();
    await settle();
    await run('http://site.test/e', {}, setsCookie);
    expect(setsCookie).toHaveBeenCalledTimes(2);
  });
});

describe('sharedMicrocache', () => {
  it('serves pages rendered without the session to everyone, cookie or not', async () => {
    const next = vi.fn(async () => page('<p>player</p>'));
    const run = async (headers: Record<string, string>) => (await sharedMicrocache({ request: new Request('http://site.test/embed/x', { headers }) } as Args, next as Parameters<typeof microcache>[1])) as Response;
    await (await run({ cookie: 'session=1' })).text();
    await settle();
    const second = await run({ 'sec-fetch-site': 'cross-site' });
    expect(second.headers.get('x-cache')).toBe('HIT');
    expect(await second.text()).toBe('<p>player</p>');
    expect(next).toHaveBeenCalledTimes(1);
  });
});
