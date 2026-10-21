import { describe, expect, it } from 'vitest';
import type { Timeline, TimelineSegment, TimelineSpeaker } from '../api/timeline';
import { BEAT_DECAY_MS, beatAt, cameraAt, flashAt, glowColorAt, grooveAt, mixColor, roundCardAt, roundCards, withAlpha } from './groove';

const BEAT = { bpm: 92, offset_ms: 370, accent: 0 };
const PERIOD = 60_000 / 92;

const speaker = (id: string, color: string): TimelineSpeaker => ({ id, name: id, role: id === 'mc' ? 'moderator' : 'debater', model: 'm', color, mascot: 'orb', avatar_url: null, voice_id: null });

const seg = (speaker_id: string, round_id: string, turn_type: string, start_ms: number, end_ms: number): TimelineSegment => ({
  seq_index: start_ms,
  speaker_id,
  speaker_name: speaker_id,
  round_id,
  turn_type,
  start_ms,
  end_ms,
  audio: 'a.wav',
  text: 'x',
  words: [],
  levels: [0, 1, 0.5],
  levels_hz: 20,
  note: null,
});

const timeline = (segments: TimelineSegment[], extra: Partial<Timeline> = {}): Timeline =>
  ({ speakers: [speaker('mc', '#FFC46B'), speaker('a', '#6C9CFF'), speaker('b', '#FF7A66')], segments, ...extra }) as Timeline;

// A battle as the media build lays it out: the MC over the intro, a break before round 2.
const BATTLE = timeline(
  [
    seg('mc', 'round_1', 'moderator_intro', 600, 24_920),
    seg('a', 'round_1', 'verse', 27_529, 40_574),
    seg('b', 'round_1', 'verse', 40_574, 53_619),
    seg('b', 'round_2', 'verse', 58_837, 71_882),
    seg('a', 'round_2', 'verse', 71_882, 84_927),
    seg('mc', 'verdict', 'verdict', 85_527, 128_887),
  ],
  { beat: BEAT },
);

describe('beatAt', () => {
  it('flashes on every beat and fades before the next', () => {
    expect(beatAt(BEAT, 370).pulse).toBeCloseTo(1);
    expect(beatAt(BEAT, 370 + 10 * PERIOD).pulse).toBeCloseTo(1);
    expect(beatAt(BEAT, 370 + BEAT_DECAY_MS).pulse).toBeCloseTo(Math.exp(-1));
    expect(beatAt(BEAT, 370 + PERIOD - 1).pulse).toBeLessThan(0.05);
  });

  it('tells the kick beats and counts beats for the bars', () => {
    expect(beatAt(BEAT, 400).strong).toBe(true);
    expect(beatAt(BEAT, 400 + PERIOD).strong).toBe(false);
    expect(beatAt({ ...BEAT, accent: 1 }, 400 + PERIOD).strong).toBe(true);
    // Before the grid's first beat too.
    expect(beatAt(BEAT, 100).strong).toBe(false);
    expect(beatAt(BEAT, 370 + 8 * PERIOD).phase).toBeCloseTo(8);
  });

  it('follows the loudness without a grid', () => {
    const g = grooveAt({ beat: null }, BATTLE.segments[1], BATTLE.segments[1].start_ms + 50);
    expect(g.pulse).toBeCloseTo(1);
    expect(grooveAt({ beat: null }, null, 0).pulse).toBe(0);
  });
});

describe('colours', () => {
  it('mixes and fades', () => {
    expect(mixColor('#000000', '#ffffff', 0.5)).toBe('#808080');
    expect(mixColor('#6C9CFF', '#FF7A66', 0)).toBe('#6c9cff');
    expect(withAlpha('#FF7A66', 0.25)).toBe('rgba(255,122,102,0.250)');
  });

  it('turns from the last speaker to the next one', () => {
    expect(glowColorAt(BATTLE, 0, '#111111')).toBe('#111111');
    expect(glowColorAt(BATTLE, 27_529, '#111111')).toBe('#ffc46b');
    expect(glowColorAt(BATTLE, 27_529 + 5000, '#111111')).toBe('#6c9cff');
    expect(glowColorAt(BATTLE, 40_574 + 350, '#111111')).toBe(mixColor('#6C9CFF', '#FF7A66', 0.5));
  });
});

describe('roundCards', () => {
  it('slams a battle card on a kick before the first verse of every round', () => {
    const cards = roundCards(BATTLE);
    expect(cards.map((c) => c.label)).toEqual(['ROUND 1', 'ROUND 2']);
    for (const [card, after, verse] of [
      [cards[0], 24_920, 27_529],
      [cards[1], 53_619, 58_837],
    ] as const) {
      expect(card.slamMs).toBeGreaterThanOrEqual(after);
      expect(card.slamMs).toBeLessThan(verse);
      expect(beatAt(BEAT, card.slamMs + 1).strong).toBe(true);
      expect(card.endMs).toBe(verse + 150);
      expect(card.loud).toBe(true);
    }
    expect(roundCardAt(BATTLE, cards[1].slamMs + 10)?.label).toBe('ROUND 2');
    expect(roundCardAt(BATTLE, 30_000)).toBeNull();
  });

  it('gives a debate a quiet card from round 2 on', () => {
    const debate = timeline([seg('mc', 'round_1', 'moderator_intro', 0, 5000), seg('a', 'round_1', 'opening', 5600, 9000), seg('mc', 'round_2', 'moderator_transition', 9600, 12_000), seg('a', 'round_2', 'rebuttal', 12_600, 15_000), seg('mc', 'verdict', 'verdict', 15_600, 20_000)]);
    expect(roundCards(debate)).toEqual([{ label: 'ROUND 2', slamMs: 9600, endMs: 11_100, loud: false }]);
  });
});

describe('the camera', () => {
  it('breathes within a percent, shakes only as a loud card lands', () => {
    for (let ms = 0; ms < 40_000; ms += 777) {
      const cam = cameraAt(ms, null, null);
      expect(cam.scale).toBeGreaterThanOrEqual(1);
      expect(cam.scale).toBeLessThanOrEqual(1.006);
      expect([cam.x, cam.y]).toEqual([0, 0]);
    }
    const card = roundCards(BATTLE)[1];
    expect(Math.abs(cameraAt(card.slamMs + 30, null, card).x)).toBeGreaterThan(1);
    expect(cameraAt(card.slamMs + 400, null, card).x).toBe(0);
    expect(cameraAt(card.slamMs + 30, null, { ...card, loud: false }).x).toBe(0);
    expect(flashAt(card, card.slamMs)).toBeCloseTo(0.14);
    expect(flashAt(card, card.slamMs - 50)).toBe(0);
    expect(flashAt(card, card.slamMs + 300)).toBe(0);
  });
});
