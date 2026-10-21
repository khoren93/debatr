import type { Timeline } from '../api/timeline';
import type { ScoreboardScene } from '../api/visuals';
import { timelineFormat } from '../lib/formats';
import { roundCards } from './groove';
import { winnerRevealMs } from './reveal';

/**
 * The crowd and the studio audience of the videos, free of Remotion (unit-tested): which sound
 * plays when. The files are not in git: scripts/sfx/generate.py makes and installs them into
 * public/sfx with a manifest.json of each kind's files, and a server gets the folder by hand.
 * The video plays them over the show's track at the moments it hits on screen, so the player,
 * the MP4 and the embed hear the same (the MP3 download is the show's track alone); without the
 * manifest (or a kind's files) it plays without them.
 */

/** How loud each kind plays over the show. */
export const SFX_VOLUME = {
  'crowd-ooh': 0.55,
  'crowd-erupt': 0.6,
  'crowd-laugh': 0.5,
  impact: 0.5,
  'crowd-roar': 0.6,
  'studio-ooh': 0.35,
  applause: 0.4,
  'studio-laugh': 0.35,
  'studio-murmur': 0.35,
  whoosh: 0.3,
  'verdict-sting': 0.4,
} as const;

export type SfxKind = keyof typeof SFX_VOLUME;

/** public/sfx/manifest.json: the files of every kind (generate.py install). */
export type SfxManifest = Partial<Record<SfxKind, string[]>>;

const FILE = /^[a-z0-9-]+\.mp3$/;

/** The manifest as fetched, read defensively: known kinds, plain file names only. */
export const readManifest = (raw: unknown): SfxManifest => {
  const files = (raw as { files?: unknown } | null)?.files;
  const out: SfxManifest = {};
  if (!files || typeof files !== 'object') return out;
  for (const kind of Object.keys(SFX_VOLUME) as SfxKind[]) {
    const list = (files as Record<string, unknown>)[kind];
    if (Array.isArray(list)) out[kind] = list.filter((f): f is string => typeof f === 'string' && FILE.test(f));
  }
  return out;
};

export interface Cue {
  kind: SfxKind;
  file: string; // "crowd-ooh-2-t3.mp3"
  atMs: number; // on the show's track
  volume: number;
}

/** No sound is longer (a cue's sequence ends here). */
export const SFX_MAX_MS = 4500;
/** The crowd reacts a beat after the punchline's last word. */
const REACT_MS = 60;
/** The drum roll starts this long before the winner is crowned. */
const STING_LEAD_MS = 1800;
/** The audience murmurs as a figure is shown contradicted (the scene's fact-check note). */
const MURMUR_MS = 700;

/** Crowd reactions play: as the media build was asked, else the format's default (older
 *  timelines: battles yes, debates no). */
export const sfxOn = (timeline: Pick<Timeline, 'sfx' | 'format' | 'segments'>): boolean => timeline.sfx ?? timelineFormat(timeline).crowdSounds;

const hash = (text: string): number => {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
};

type Planned = { kind: SfxKind; atMs: number };

const plans = new WeakMap<Timeline, Planned[]>();

/** When which kind plays, in track order: a battle's crowd on its punchlines (erupting on the
 *  round's best, laughing at a roast), a low hit as a round card slams and on the best punch, a
 *  roar as the winner is crowned; a debate's audience on its zingers, a whoosh into round cards,
 *  a murmur at a contradicted figure, a drum roll and applause for the verdict. */
const plan = (timeline: Timeline): Planned[] => {
  const cached = plans.get(timeline);
  if (cached) return cached;
  const raw: Planned[] = [];
  if (sfxOn(timeline)) {
    const battle = timelineFormat(timeline).id === 'rap_battle';
    for (const m of timeline.moments ?? []) {
      if (m.kind === 'punchline') {
        raw.push({ kind: m.big ? 'crowd-erupt' : m.funny ? 'crowd-laugh' : 'crowd-ooh', atMs: m.end_ms + REACT_MS });
        if (m.big) raw.push({ kind: 'impact', atMs: m.end_ms });
      } else {
        raw.push({ kind: m.funny ? 'studio-laugh' : 'studio-ooh', atMs: m.end_ms + REACT_MS });
      }
    }
    for (const card of roundCards(timeline)) raw.push(card.loud ? { kind: 'impact', atMs: card.slamMs } : { kind: 'whoosh', atMs: card.slamMs - 120 });
    for (const visual of timeline.visuals ?? []) {
      if (visual.scene.type === 'scoreboard') {
        const crowned = visual.start_ms + winnerRevealMs(visual.scene as ScoreboardScene);
        if (battle) raw.push({ kind: 'crowd-roar', atMs: crowned });
        else raw.push({ kind: 'verdict-sting', atMs: Math.max(visual.start_ms, crowned - STING_LEAD_MS) }, { kind: 'applause', atMs: crowned });
      } else if (!battle && visual.check?.verdict === 'disputed') {
        raw.push({ kind: 'studio-murmur', atMs: visual.start_ms + MURMUR_MS });
      }
    }
  }
  raw.sort((a, b) => a.atMs - b.atMs);
  plans.set(timeline, raw);
  return raw;
};

/** Every sound of the show with its file: one of the kind's files picked at random but the same
 *  on every render (seeded by the debate and the cue), never the file the kind played last; a
 *  kind without files is left out. */
export const sfxCues = (timeline: Timeline, manifest: SfxManifest): Cue[] => {
  const counts = new Map<SfxKind, number>();
  const last = new Map<SfxKind, string>();
  const cues: Cue[] = [];
  for (const { kind, atMs } of plan(timeline)) {
    const pool = manifest[kind] ?? [];
    if (pool.length === 0) continue;
    const n = counts.get(kind) ?? 0;
    counts.set(kind, n + 1);
    let i = hash(`${timeline.debate_id}:${kind}:${n}`) % pool.length;
    if (pool.length > 1 && pool[i] === last.get(kind)) i = (i + 1) % pool.length;
    last.set(kind, pool[i]);
    cues.push({ kind, file: pool[i], atMs: Math.round(atMs), volume: SFX_VOLUME[kind] });
  }
  return cues;
};
