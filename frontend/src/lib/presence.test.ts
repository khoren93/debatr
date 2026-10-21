import { describe, expect, it } from 'vitest';
import { IDLE_MS, VISIT_IDLE_MS, engagedSince, visitExpired } from './presence';

describe('presence', () => {
  it('counts the time a page is visible, up to the idle limit after the last input', () => {
    expect(engagedSince(null, 10_000, 0)).toBe(0);
    expect(engagedSince(1000, 61_000, 60_000)).toBe(60_000);
    // A video watched without a click: counted for IDLE_MS after the last input, not after.
    expect(engagedSince(0, IDLE_MS + 3_600_000, 0)).toBe(IDLE_MS);
    expect(engagedSince(5000, 4000, 0)).toBe(0);
  });

  it('ends a visit after half an hour without activity', () => {
    expect(visitExpired(0, VISIT_IDLE_MS)).toBe(false);
    expect(visitExpired(0, VISIT_IDLE_MS + 1)).toBe(true);
  });
});
