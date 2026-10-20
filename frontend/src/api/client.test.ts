import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, getErrorMessage, getErrorStatus } from './client';

const reply = (status: number, body: string | null, headers: Record<string, string> = {}) => vi.fn(async () => new Response(body, { status, headers }));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api', () => {
  it('sends JSON with the session cookie and returns the parsed answer', async () => {
    const fetchMock = reply(200, '{"id":"d1"}');
    vi.stubGlobal('fetch', fetchMock);
    const res = await api.post<{ id: string }>('/debates', { topic: 'Tabs?' }, { headers: { 'X-TTS-Key': 'k' } });
    expect(res.data).toEqual({ id: 'd1' });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/debates');
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"topic":"Tabs?"}');
    expect(init.credentials).toBe('include');
    expect(init.headers).toMatchObject({ 'Content-Type': 'application/json', 'X-TTS-Key': 'k' });
  });

  it('builds the query from params and honours baseURL', async () => {
    const fetchMock = reply(200, '[]');
    vi.stubGlobal('fetch', fetchMock);
    await api.get('/gallery', { params: { sort: 'new', model: undefined, page: 2, premium_voices: false } });
    await api.get('/api/media/files/x/timeline.json', { baseURL: '' });
    expect(fetchMock.mock.calls.map((c) => (c as unknown as [string])[0])).toEqual(['/api/gallery?sort=new&page=2&premium_voices=false', '/api/media/files/x/timeline.json']);
    expect((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body).toBeUndefined();
  });

  it('keeps text answers as text and reads headers', async () => {
    vi.stubGlobal('fetch', reply(200, 'a,b\n1,2', { 'Content-Disposition': 'attachment; filename="ledger.csv"' }));
    const res = await api.get<string>('/billing/transactions.csv', { responseType: 'text' });
    expect(res.data).toBe('a,b\n1,2');
    expect(res.headers.get('content-disposition')).toContain('ledger.csv');
  });

  it('answers an empty body with an empty string', async () => {
    vi.stubGlobal('fetch', reply(204, null));
    expect((await api.delete('/debates/d1')).data).toBe('');
  });

  it('throws ApiError with the status and the API detail', async () => {
    vi.stubGlobal('fetch', reply(402, '{"detail":"Not enough credits"}'));
    const err = await api.post('/debates', {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(getErrorStatus(err)).toBe(402);
    expect(getErrorMessage(err)).toBe('Not enough credits');
  });

  it('turns lost connections into a network error without a status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    const err = await api.get('/auth/me').catch((e: unknown) => e);
    expect(getErrorStatus(err)).toBeNull();
    expect(getErrorMessage(err)).toBe('Network error: could not reach the server');
  });
});

describe('error helpers', () => {
  it('read validation errors and the console axios errors', () => {
    const validation = new ApiError('failed', { status: 422, data: { detail: [{ msg: 'Value error, Topic is too long' }] }, headers: new Headers() });
    expect(getErrorMessage(validation)).toBe('Topic is too long');
    expect(getErrorMessage(new ApiError('failed', { status: 500, data: '<html>', headers: new Headers() }))).toBe('Request failed (500)');
    // The shape of an axios error (the admin console's client).
    const axiosLike = Object.assign(new Error('Request failed'), { isAxiosError: true, response: { status: 409, data: { detail: 'Busy' } } });
    expect(getErrorStatus(axiosLike)).toBe(409);
    expect(getErrorMessage(axiosLike)).toBe('Busy');
    expect(getErrorMessage(new Error('boom'))).toBe('boom');
  });
});
