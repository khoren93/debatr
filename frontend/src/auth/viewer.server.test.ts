import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { firstParty, readViewer } from './viewer.server';

const request = (headers: Record<string, string>) => new Request('http://site.test/library', { headers });

describe('readViewer', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('knows a first-party visit without cookies is anonymous, without asking the API', async () => {
    for (const site of ['same-origin', 'same-site', 'none']) {
      expect(await readViewer(request({ 'sec-fetch-site': site }))).toEqual({ user: null, known: true });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('cannot tell for a link from another site (SameSite=Strict kept the cookie home)', async () => {
    expect(await readViewer(request({ 'sec-fetch-site': 'cross-site' }))).toEqual({ user: null, known: false });
    expect(await readViewer(request({}))).toEqual({ user: null, known: false });
    expect(firstParty(request({ 'sec-fetch-site': 'cross-site' }))).toBe(false);
  });

  it('asks the API with the cookie', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ id: 'u1', email: 'a@b.c' }), { status: 200 }));
    expect(await readViewer(request({ cookie: 'session=abc', 'sec-fetch-site': 'cross-site' }))).toEqual({ user: { id: 'u1', email: 'a@b.c' }, known: true });
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('cookie')).toBe('session=abc');
  });

  it('leaves it to the browser when the API fails', async () => {
    fetchMock.mockResolvedValue(new Response('down', { status: 502 }));
    expect(await readViewer(request({ cookie: 'session=abc' }))).toEqual({ user: null, known: false });
  });
});
