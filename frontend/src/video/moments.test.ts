import { describe, expect, it } from 'vitest';
import type { TimelineMoment } from '../api/timeline';
import { hitAt, inMoment, momentAt } from './moments';

const moment = (kind: TimelineMoment['kind'], start_ms: number, end_ms: number, big = false): TimelineMoment => ({ seq_index: 1, speaker_id: 'a', kind, quote: 'q', start_ms, end_ms, big, funny: false });

const PUNCH = moment('punchline', 10_000, 12_000);
const BIG = moment('punchline', 20_000, 21_000, true);
const ZINGER = moment('zinger', 30_000, 31_000);
const TIMELINE = { moments: [PUNCH, BIG, ZINGER] };

describe('hitAt', () => {
  it('pushes in while the line is said and lets go after it', () => {
    expect(hitAt(TIMELINE, 9_000)).toBeNull();
    const pushes = [9_900, 10_500, 11_000, 11_900, 12_100, 12_400, 12_600, 12_740].map((ms) => hitAt(TIMELINE, ms)?.push ?? 0);
    expect(pushes[0]).toBeLessThan(pushes[1]);
    expect(pushes[3]).toBeLessThanOrEqual(0.03);
    expect(pushes[4]).toBeCloseTo(0.03, 3); // held after the last word
    expect(pushes[6]).toBeLessThan(pushes[5]);
    expect(hitAt(TIMELINE, 12_760)).toBeNull();
  });

  it('flashes, shakes and makes the other rapper flinch as a punchline lands', () => {
    const before = hitAt(TIMELINE, 11_990)!;
    expect([before.flash, before.flinch, before.landed, before.shake.x]).toEqual([0, 0, 0, 0]);
    const land = hitAt(TIMELINE, 12_000)!;
    expect(land.flash).toBeCloseTo(0.1);
    expect(land.flinch).toBe(1);
    const shaking = hitAt(TIMELINE, 12_050)!;
    expect(Math.abs(shaking.shake.x) + Math.abs(shaking.shake.y)).toBeGreaterThan(1);
    expect(hitAt(TIMELINE, 12_300)!.landed).toBe(1);
    expect(hitAt(TIMELINE, 12_400)!.shake).toEqual({ x: 0, y: 0 });
  });

  it('hits the round’s best punchline harder, a zinger softly', () => {
    expect(hitAt(TIMELINE, 21_000)!.flash).toBeCloseTo(0.15);
    const zinger = hitAt(TIMELINE, 31_000)!;
    expect(zinger.flash).toBeCloseTo(0.04);
    expect([zinger.flinch, zinger.shake.x, zinger.shake.y]).toEqual([0, 0, 0]);
    expect(hitAt(TIMELINE, 31_250)!.push).toBeCloseTo(0.015, 3);
  });

  it('works without moments (older timelines)', () => {
    expect(momentAt({}, 10_000)).toBeNull();
    expect(hitAt({ moments: [] }, 10_000)).toBeNull();
  });
});

describe('inMoment', () => {
  it('takes the words inside the line, with a little slack', () => {
    expect(inMoment(PUNCH, 10_000, 10_300)).toBe(true);
    expect(inMoment(PUNCH, 11_700, 12_020)).toBe(true);
    expect(inMoment(PUNCH, 12_100, 12_300)).toBe(false);
    expect(inMoment(null, 10_000, 10_300)).toBe(false);
  });
});
