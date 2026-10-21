import { describe, expect, it } from 'vitest';
import type { TimelineWord } from '../api/timeline';
import { alignWords, lineAt, rhymeKey, rhymes, verseLines } from './lyrics';

const timed = (spec: string): TimelineWord[] =>
  spec.split(' ').map((w, i) => ({ w, s: i * 300, e: i * 300 + 250 }));

// A verse of a real battle (6bebf448, seq 2): the track's words end in its directions.
const VERSE = {
  text: 'You mix up physical goods with intellectual rights;\nI track how licenses fund maintenance and hosted sites.\nForced ownership breaks the live services you claim to love,\nWhile Claude, you rent your tokens from AWS above.',
  start_ms: 40574,
  end_ms: 53619,
  words: [
    ['You', 86, 166], ['mix', 226, 386], ['up', 446, 566], ['physical', 586, 946], ['goods', 1086, 1346], ['with', 1386, 1506], ['intellectual', 1566, 2286], ['rights;', 2406, 2646],
    ['I', 2726, 2766], ['track', 2826, 3006], ['how', 3046, 3146], ['licenses', 3186, 3666], ['fund', 3686, 3826], ['maintenance', 3866, 4306], ['and', 4346, 4406], ['hosted', 4486, 4866], ['sites.', 5006, 5306],
    ['Forced', 5466, 5706], ['ownership', 5826, 6306], ['breaks', 6406, 6626], ['the', 6646, 6746], ['live', 6786, 6966], ['services', 7086, 7546], ['you', 7586, 7666], ['claim', 7746, 7986], ['to', 8046, 8166], ['love,', 8246, 8506],
    ['While', 8546, 8626], ['Claude,', 8726, 9026], ['you', 9246, 9326], ['rent', 9366, 9486], ['your', 9526, 9626], ['tokens', 9686, 9986], ['from', 10026, 10146], ['AWS', 10186, 10846], ['above.', 10906, 11426],
    ['scratch,', 11426, 11466], ['crowd', 11426, 11466],
  ].map(([w, s, e]) => ({ w: String(w), s: Number(s), e: Number(e) })),
};

describe('verseLines', () => {
  it('times every line of a real verse and drops the directions the track sang', () => {
    const lines = verseLines(VERSE);
    expect(lines.map((l) => l.words.length)).toEqual([8, 9, 10, 9]);
    expect(lines[0].startMs).toBe(40574 + 86);
    expect(lines[1].startMs).toBe(40574 + 2726);
    expect(lines[3].words.at(-1)).toEqual({ text: 'above.', fromMs: 40574 + 10906, toMs: 40574 + 11426 });
    expect(lines[3].endMs).toBe(40574 + 11426);
    // Lines follow each other.
    lines.slice(1).forEach((line, i) => expect(line.startMs).toBeGreaterThanOrEqual(lines[i].endMs));
  });

  it('gives a word the track swallowed a time between its neighbours', () => {
    const lines = verseLines({ text: 'one two three four', start_ms: 1000, end_ms: 5000, words: timed('one two four') });
    const [one, two, three, four] = lines[0].words;
    expect(one.fromMs).toBe(1000);
    expect(two.toMs).toBe(1000 + 550);
    expect(three.fromMs).toBe(two.toMs);
    expect(three.toMs).toBe(four.fromMs);
    expect(four.fromMs).toBe(1000 + 600);
  });

  it('spreads a verse without timed words over its segment', () => {
    const lines = verseLines({ text: 'a b\nc d', start_ms: 0, end_ms: 4000, words: [] });
    expect(lines.map((l) => [l.startMs, l.endMs])).toEqual([
      [0, 2000],
      [2000, 4000],
    ]);
  });

  it('maps by position when the track sang other words', () => {
    const lines = verseLines({ text: 'alpha beta\ngamma delta', start_ms: 0, end_ms: 4000, words: timed('w x y z') });
    expect(lines.map((l) => l.startMs)).toEqual([0, 600]);
  });

  it('matches curly quotes, apostrophes and case', () => {
    expect(alignWords(['Your', '“keep', 'it', 'neat”', "logic's"], ['your', 'keep', 'it', 'neat', 'logic’s'])).toEqual([0, 1, 2, 3, 4]);
  });
});

describe('rhymes', () => {
  it.each([
    ['gaps', 'flaps'],
    ['mode', 'load'],
    ['farm,', 'harm.'],
    ['love,', 'above.'],
    ['cheats,', 'repeats.'],
    ['claim:', 'game.'],
    ['file,', 'aisle.'],
    ['flow.', 'show.'],
    ['go.', 'flow.'],
    ['ночь', 'дочь'],
    ['бой', 'твой'],
  ])('%s / %s', (a, b) => expect(rhymes(a, b)).toBe(true));

  it.each([
    ['rights;', 'sites.'],
    ['code', 'farm'],
    ['the', ''],
  ])('%s / %s do not', (a, b) => expect(rhymes(a, b)).toBe(false));

  it('drops a silent e', () => {
    expect(rhymeKey('mode')).toEqual({ word: 'mod', vowels: 'o', coda: 'd' });
    expect(rhymeKey('Flow.')).toEqual({ word: 'flow', vowels: 'ow', coda: '' });
  });

  it('marks the lines of a verse whose ends rhyme', () => {
    expect(verseLines(VERSE).map((l) => l.rhymes)).toEqual([false, false, true, true]);
  });
});

describe('lineAt', () => {
  it('is the last line that started', () => {
    const lines = verseLines(VERSE);
    expect(lineAt(lines, 0)).toBe(-1);
    expect(lineAt(lines, 40574 + 3000)).toBe(1);
    expect(lineAt(lines, 99_999)).toBe(3);
  });
});
