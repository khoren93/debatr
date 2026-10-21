import { describe, expect, it } from 'vitest';
import type { Timeline, TimelineMoment, TimelineSegment } from '../api/timeline';
import type { TimelineVisual } from '../api/visuals';
import { roundCards } from './groove';
import { readManifest, sfxCues, sfxOn, type SfxManifest } from './sfx';

const seg = (speaker_id: string, round_id: string, turn_type: string, start_ms: number, end_ms: number): TimelineSegment => ({ seq_index: start_ms, speaker_id, speaker_name: speaker_id, round_id, turn_type, start_ms, end_ms, audio: 'a.wav', text: 'x', words: [], levels: [], levels_hz: 20, note: null });

const moment = (kind: TimelineMoment['kind'], end_ms: number, extra: Partial<TimelineMoment> = {}): TimelineMoment => ({ seq_index: 1, speaker_id: 'a', kind, quote: 'q', start_ms: end_ms - 2000, end_ms, big: false, funny: false, ...extra });

const board = (start_ms: number, rounds = 2): TimelineVisual =>
  ({ id: 'v', key: 'k', speaker_id: 'judge', seq_index: 9, start_ms, end_ms: start_ms + 9000, item_ms: [], scene: { type: 'scoreboard', title: '', anchor: '', speaker_ids: ['a', 'b'], winner_id: 'a', rounds: Array.from({ length: rounds }, (_, i) => ({ round: i + 1, scores: { a: 8, b: 7 } })), decide_ms: 4000 } }) as unknown as TimelineVisual;

const BATTLE = {
  debate_id: 'battle-1',
  format: 'rap_battle',
  speakers: [],
  segments: [seg('mc', 'round_1', 'moderator_intro', 600, 24_920), seg('a', 'round_1', 'verse', 27_529, 40_574), seg('b', 'round_1', 'verse', 40_574, 53_619), seg('b', 'round_2', 'verse', 58_837, 71_882), seg('mc', 'verdict', 'verdict', 72_500, 110_000)],
  beat: { bpm: 92, offset_ms: 370, accent: 0 },
  moments: [moment('punchline', 35_600, { big: true }), moment('punchline', 52_000), moment('punchline', 70_000, { funny: true }), moment('punchline', 71_000)],
  visuals: [board(80_000)],
} as unknown as Timeline;

// Three takes of every sound, as generate.py install lays them out.
const takes = (kind: string, sounds: number) => Array.from({ length: sounds * 3 }, (_, i) => `${kind}-${Math.floor(i / 3) + 1}-t${(i % 3) + 1}.mp3`);
const ALL: SfxManifest = readManifest({
  files: {
    'crowd-ooh': takes('crowd-ooh', 4),
    'crowd-erupt': takes('crowd-erupt', 3),
    'crowd-laugh': takes('crowd-laugh', 2),
    impact: takes('impact', 2),
    'crowd-roar': takes('crowd-roar', 2),
    'studio-ooh': takes('studio-ooh', 3),
    applause: takes('applause', 2),
    'studio-laugh': takes('studio-laugh', 1),
    'studio-murmur': takes('studio-murmur', 1),
    whoosh: takes('whoosh', 2),
    'verdict-sting': takes('verdict-sting', 1),
  },
});

describe('readManifest', () => {
  it('keeps known kinds and plain file names only', () => {
    expect(readManifest({ files: { 'crowd-ooh': ['a.mp3', '../x.mp3', 7, 'B.mp3'], nope: ['c.mp3'] } })).toEqual({ 'crowd-ooh': ['a.mp3'] });
    expect(readManifest(null)).toEqual({});
    expect(readManifest('junk')).toEqual({});
  });
});

describe('sfxCues', () => {
  it('gives a battle its crowd on the punchlines, hits on the cards, a roar for the winner', () => {
    const cues = sfxCues(BATTLE, ALL);
    const [card1, card2] = roundCards(BATTLE);
    expect(cues.map((c) => [c.kind, c.atMs])).toEqual([
      ['impact', Math.round(card1.slamMs)],
      ['impact', 35_600],
      ['crowd-erupt', 35_660],
      ['crowd-ooh', 52_060],
      ['impact', Math.round(card2.slamMs)],
      ['crowd-laugh', 70_060],
      ['crowd-ooh', 71_060],
      ['crowd-roar', 80_000 + 4000],
    ]);
    // A file of the kind, the same on every render, never the kind's last one again.
    for (const cue of cues) expect(ALL[cue.kind]).toContain(cue.file);
    expect(sfxCues(BATTLE, ALL)).toEqual(cues);
    const oohs = cues.filter((c) => c.kind === 'crowd-ooh').map((c) => c.file);
    expect(oohs[0]).not.toBe(oohs[1]);
    // Another debate hears other takes.
    const other = sfxCues({ ...BATTLE, debate_id: 'battle-2' } as Timeline, ALL).map((c) => c.file);
    expect(other).not.toEqual(cues.map((c) => c.file));
  });

  it('is off for a debate unless asked, and quiet then', () => {
    const debate = { ...BATTLE, format: 'debate', debate_id: 'd', beat: null, segments: [seg('mc', 'round_1', 'moderator_intro', 0, 5000), seg('a', 'round_1', 'opening', 5600, 9000), seg('mc', 'round_2', 'moderator_transition', 9600, 12_000), seg('a', 'round_2', 'closing', 12_600, 15_000)], moments: [moment('zinger', 8000), moment('zinger', 14_000, { funny: true })], visuals: [board(16_000, 0), { ...board(6000, 0), scene: { type: 'stat' }, check: { verdict: 'disputed' } } as unknown as TimelineVisual] } as unknown as Timeline;
    expect(sfxOn(debate)).toBe(false);
    expect(sfxCues(debate, ALL)).toEqual([]);
    const asked = { ...debate, sfx: true } as Timeline;
    expect(sfxCues(asked, ALL).map((c) => [c.kind, c.atMs])).toEqual([
      ['studio-murmur', 6700],
      ['studio-ooh', 8060],
      ['whoosh', 9480],
      ['studio-laugh', 14_060],
      ['verdict-sting', 16_000],
      ['applause', 16_000 + 700 + 2 * 250],
    ]);
    expect(sfxCues(asked, ALL).every((c) => c.volume < 0.5)).toBe(true);
  });

  it('follows the build’s choice over the format', () => {
    expect(sfxOn({ ...BATTLE, sfx: false })).toBe(false);
    expect(sfxCues({ ...BATTLE, sfx: false } as Timeline, ALL)).toEqual([]);
    expect(sfxOn({ format: undefined, segments: BATTLE.segments })).toBe(true); // an older battle
  });
});

describe('without the sounds', () => {
  it('plays nothing without the manifest, and leaves out the kinds it lacks', () => {
    expect(sfxCues(BATTLE, {})).toEqual([]);
    const onlyOoh = sfxCues(BATTLE, { 'crowd-ooh': ['crowd-ooh-1-t1.mp3'] });
    expect(onlyOoh.map((c) => [c.kind, c.file])).toEqual([
      ['crowd-ooh', 'crowd-ooh-1-t1.mp3'],
      ['crowd-ooh', 'crowd-ooh-1-t1.mp3'], // one file: it repeats
    ]);
  });
});
