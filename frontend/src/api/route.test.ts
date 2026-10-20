import { describe, expect, it } from 'vitest';
import { ApiError } from './client';
import { routeError, routeErrorOf, toQuery } from './route';

const answer = (status: number, data: unknown) => new ApiError('failed', { status, data, headers: new Headers() });

describe('toQuery', () => {
  it('drops undefined and null, keeps false and zero', () => {
    expect(toQuery({ a: 'x y', b: undefined, c: null, d: false, e: 0 })).toBe('?a=x+y&d=false&e=0');
    expect(toQuery({ a: undefined })).toBe('');
  });
});

describe('routeError', () => {
  it('keeps a client error with its detail', () => {
    const err = routeError(answer(404, { detail: 'Debate not found' }));
    expect(err.init?.status).toBe(404);
    expect(err.data).toEqual({ status: 404, detail: 'Debate not found' });
  });

  it('turns server errors and lost connections into 503', () => {
    expect(routeError(answer(502, { detail: 'Bad gateway' })).init?.status).toBe(503);
    expect(routeError(new ApiError('Failed to fetch', null)).data.status).toBe(503);
    expect(routeError(new Error('boom')).init?.status).toBe(503);
  });
});

describe('routeErrorOf', () => {
  it('reads route error responses and plain exceptions', () => {
    // The shape of React Router's ErrorResponse (what a loader's thrown data() becomes).
    const response = (status: number, data: unknown) => ({ status, statusText: 'Status', internal: false, data });
    expect(routeErrorOf(response(403, { status: 403, detail: 'Private' }))).toEqual({ status: 403, detail: 'Private' });
    expect(routeErrorOf(response(404, 'Not Found'))).toEqual({ status: 404, detail: 'Not Found' });
    expect(routeErrorOf(response(404, null))).toEqual({ status: 404, detail: 'Status' });
    expect(routeErrorOf(new Error('kaput'))).toEqual({ status: 500, detail: 'kaput' });
  });
});
