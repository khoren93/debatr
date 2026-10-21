import type { TimelineSegment, TimelineWord } from '../api/timeline';

/**
 * A rap verse as the video shows it: line by line, each word timed on the track.
 *
 * The verse text holds one line per bar; the generated track times the words it rapped, which
 * are the same words nearly one to one (a stray "goes" or "scratch, crowd" from the section's
 * directions now and then, a word swallowed). The lines are matched to the timed words in order;
 * words the track lacks get times between their neighbours, and a verse without timed words is
 * spread evenly over its segment. Pure: no Remotion, unit-tested.
 */

export interface LyricWord {
  text: string; // as written in the verse, punctuation kept
  fromMs: number; // absolute on the track
  toMs: number;
}

export interface LyricLine {
  text: string;
  words: LyricWord[];
  startMs: number;
  endMs: number;
  /** The line's last word rhymes with the end of a line next to it (AABB) or two away (ABAB). */
  rhymes: boolean;
}

const MIN_WORD_MS = 120;
/** Below this share of matched words the timed words are not this text: map them by position. */
const MIN_MATCHED = 0.3;

const norm = (text: string) => text.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');

const same = (a: string, b: string) => a === b || (a.length >= 4 && b.length >= 4 && (a.startsWith(b) || b.startsWith(a)));

/** Index of the timed word each written word matched (-1: none), by longest common subsequence. */
export const alignWords = (written: string[], timed: string[]): number[] => {
  const a = written.map(norm);
  const b = timed.map(norm);
  const n = a.length;
  const m = b.length;
  const dp: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] && same(a[i], b[j]) ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out = new Array<number>(n).fill(-1);
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] && same(a[i], b[j]) && dp[i][j] === dp[i + 1][j + 1] + 1) out[i++] = j++;
    else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
    else j++;
  }
  return out;
};

type Span = { fromMs: number; toMs: number } | null;

/** Times for the written words without one: evenly between the timed neighbours, at the
 *  average word length before the first and after the last (clamped to the segment). */
const fillGaps = (spans: Span[], startMs: number, endMs: number): { fromMs: number; toMs: number }[] => {
  const known = spans.flatMap((s) => (s ? [s] : []));
  const avg = known.length ? Math.max(MIN_WORD_MS, known.reduce((sum, s) => sum + (s.toMs - s.fromMs), 0) / known.length) : MIN_WORD_MS * 2;
  const out = spans.slice();
  let i = 0;
  while (i < out.length) {
    if (out[i]) {
      i++;
      continue;
    }
    let j = i;
    while (j < out.length && !out[j]) j++;
    const before = i > 0 ? out[i - 1] : null;
    const after = j < out.length ? out[j] : null;
    const count = j - i;
    const from = before ? before.toMs : Math.max(startMs, (after ? after.fromMs : startMs) - avg * count);
    const to = after ? after.fromMs : Math.min(endMs, from + avg * count);
    const step = Math.max(0, to - from) / count;
    for (let k = 0; k < count; k++) out[i + k] = { fromMs: from + step * k, toMs: from + step * (k + 1) };
    i = j;
  }
  return out.map((s) => s ?? { fromMs: startMs, toMs: startMs });
};

const VOWELS = new Set([...'aeiouyáéíóúàèìòùâêîôûäëïöüæœøåаеёиоуыэюяіїєў']);

const isVowel = (word: string, i: number) => VOWELS.has(word[i]) || ((word[i] === 'w' || word[i] === 'й') && i > 0 && VOWELS.has(word[i - 1]));

/** The sound a line ends on, spelled: the last vowel group and what follows it ("gaps" → a + ps;
 *  "mode" → o + d, its silent e dropped). */
export const rhymeKey = (word: string): { word: string; vowels: string; coda: string } => {
  const raw = norm(word).replace(/\d+/g, '');
  let w = raw;
  if (w.length > 3 && w.endsWith('e') && !VOWELS.has(w[w.length - 2])) w = w.slice(0, -1);
  let i = w.length - 1;
  while (i >= 0 && !isVowel(w, i)) i--;
  const codaStart = i + 1;
  while (i >= 0 && isVowel(w, i)) i--;
  return { word: w, vowels: w.slice(i + 1, codaStart), coda: w.slice(codaStart) };
};

const tail = (word: string) => norm(word).replace(/\d+/g, '').slice(-2);

/** Loose, spelling-based: the same ending, the same last two letters, or the same coda after a
 *  vowel group they share ("mode" / "load", "claim" / "game", "go" / "flow"). */
export const rhymes = (a: string, b: string): boolean => {
  const x = rhymeKey(a);
  const y = rhymeKey(b);
  if (!x.word || !y.word || !x.vowels || !y.vowels) return false;
  if (x.word === y.word) return true;
  if (x.vowels + x.coda === y.vowels + y.coda) return true;
  // As written, silent e included ("file" / "aisle").
  if (tail(a).length === 2 && tail(a) === tail(b) && x.coda !== '') return true;
  return x.coda === y.coda && [...x.vowels].some((c) => y.vowels.includes(c));
};

const cache = new WeakMap<TimelineSegment, LyricLine[]>();

/** The verse's lines with their words timed (absolute ms); cached per segment. */
export const verseLines = (seg: Pick<TimelineSegment, 'text' | 'words' | 'start_ms' | 'end_ms'>): LyricLine[] => {
  const cached = cache.get(seg as TimelineSegment);
  if (cached) return cached;
  const lines = seg.text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.split(/\s+/));
  const written = lines.flat();
  const timed: TimelineWord[] = seg.words;
  let spans: Span[];
  if (written.length === 0) {
    spans = [];
  } else if (timed.length === 0) {
    // Nothing timed: the lines share the segment evenly, the words share their line.
    const per = (seg.end_ms - seg.start_ms) / written.length;
    spans = written.map((_, i) => ({ fromMs: seg.start_ms + per * i, toMs: seg.start_ms + per * (i + 1) }));
  } else {
    const matched = alignWords(
      written,
      timed.map((w) => w.w),
    );
    const enough = matched.filter((j) => j >= 0).length >= written.length * MIN_MATCHED;
    const index = enough ? matched : written.map((_, i) => Math.min(timed.length - 1, Math.floor((i * timed.length) / written.length)));
    spans = index.map((j) => (j >= 0 ? { fromMs: seg.start_ms + timed[j].s, toMs: seg.start_ms + Math.max(timed[j].e, timed[j].s + MIN_WORD_MS) } : null));
  }
  const times = fillGaps(spans, seg.start_ms, seg.end_ms);
  let at = 0;
  const out: LyricLine[] = lines.map((tokens) => {
    const words = tokens.map((text) => ({ text, ...times[at++] }));
    return { text: tokens.join(' '), words, startMs: words[0].fromMs, endMs: words[words.length - 1].toMs, rhymes: false };
  });
  const ends = out.map((line) => line.words[line.words.length - 1].text);
  out.forEach((line, i) => {
    line.rhymes = [i - 2, i - 1, i + 1, i + 2].some((j) => j >= 0 && j < ends.length && rhymes(ends[i], ends[j]));
  });
  cache.set(seg as TimelineSegment, out);
  return out;
};

/** Index of the line being rapped at `ms` (the last one that started), -1 before the first. */
export const lineAt = (lines: LyricLine[], ms: number): number => {
  let found = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startMs <= ms) found = i;
    else break;
  }
  return found;
};
