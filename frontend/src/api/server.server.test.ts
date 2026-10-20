import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiInternalUrl, forwardedHeaders, serverApi, type ApiErrorData } from './server.server';

/** What `serverApi` threw: React Router's route error data (status, headers, body). */
const thrown = async (promise: Promise<unknown>) => {
  try {
    await promise;
  } catch (err) {
    return err as { data: ApiErrorData; init: ResponseInit | null };
  }
  throw new Error('expected a throw');
};

const visitor = (init: RequestInit = {}) =>
  new Request('http://site.test/d/abc', {
    ...init,
    headers: {
      cookie: '__Host-session=signed',
      'x-forwarded-for': '203.0.113.7',
      'user-agent': 'Mozilla/5.0 (Test)',
      'accept-language': 'ru,en;q=0.8',
      authorization: 'Bearer debatr_secret',
      'x-csrf-token': 'nope',
      ...(init.headers as Record<string, string> | undefined),
    },
  });

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('forwardedHeaders', () => {
  it('passes the visitor identity and nothing else', () => {
    const headers = forwardedHeaders(visitor());
    expect(Object.fromEntries(headers)).toEqual({
      accept: 'application/json',
      cookie: '__Host-session=signed',
      'x-forwarded-for': '203.0.113.7',
      'user-agent': 'Mozilla/5.0 (Test)',
      'accept-language': 'ru,en;q=0.8',
    });
  });

  it('leaves out headers the visitor did not send', () => {
    const headers = forwardedHeaders(new Request('http://site.test/'));
    expect([...headers.keys()]).toEqual(['accept']);
  });
});

describe('serverApi', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    vi.stubEnv('API_INTERNAL_URL', 'http://api:8000/');
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('reads the internal URL from the environment', () => {
    expect(apiInternalUrl()).toBe('http://api:8000');
    vi.stubEnv('API_INTERNAL_URL', '');
    expect(apiInternalUrl()).toBe('http://localhost:8000');
  });

  it('returns the JSON of a successful answer', async () => {
    fetchMock.mockResolvedValue(json({ slug: 'abc' }));
    await expect(serverApi<{ slug: string }>(visitor(), '/gallery/abc')).resolves.toEqual({ slug: 'abc' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://api:8000/api/gallery/abc');
    expect(new Headers(init?.headers).get('cookie')).toBe('__Host-session=signed');
    expect(new Headers(init?.headers).has('authorization')).toBe(false);
  });

  it('keeps the status of a client error with its detail', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'Debate not found' }, 404));
    const err = await thrown(serverApi(visitor(), '/gallery/missing'));
    expect(err.init?.status).toBe(404);
    expect(err.data).toEqual({ status: 404, detail: 'Debate not found' });
  });

  it('falls back to the status text when the detail is not a sentence', async () => {
    fetchMock.mockResolvedValue(json({ detail: [{ msg: 'field required' }] }, 422));
    const err = await thrown(serverApi(visitor(), '/gallery'));
    expect(err.init?.status).toBe(422);
    expect(err.data.status).toBe(422);
    expect(typeof err.data.detail).toBe('string');
  });

  it('turns a server error into 503 with Retry-After', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'boom' }, 500));
    const err = await thrown(serverApi(visitor(), '/gallery'));
    expect(err.init?.status).toBe(503);
    expect(new Headers(err.init?.headers).get('Retry-After')).toBe('30');
    expect(err.data.detail).not.toContain('boom');
  });

  it('turns an unreachable API into 503', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    const err = await thrown(serverApi(visitor(), '/gallery'));
    expect(err.init?.status).toBe(503);
  });

  it('gives up on a stuck API after the timeout', async () => {
    fetchMock.mockImplementation((_url, init) => new Promise((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))));
    const err = await thrown(serverApi(visitor(), '/gallery', { timeoutMs: 20 }));
    expect(err.init?.status).toBe(503);
  });

  it('rethrows the abort of a visitor who left', async () => {
    const left = new AbortController();
    left.abort();
    fetchMock.mockImplementation((_url, init) => Promise.reject(init?.signal?.reason));
    await expect(serverApi(visitor({ signal: left.signal }), '/gallery')).rejects.toMatchObject({ name: 'AbortError' });
  });
});
