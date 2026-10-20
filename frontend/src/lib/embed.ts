import type { CoverImage, DebateDetail, Participant } from '../api/types';
import { INTRO_MS, OUTRO_MS } from '../video/constants';

/**
 * Public debates on other sites: the player page `/embed/{slug}` (routes/embed.tsx), its address
 * and the code the Share popover hands out. Pure functions (vitest). The query mirrors backend
 * services/embed.py (`format=short` = the 9:16 Short, `t=` = start in seconds), which answers
 * oEmbed with the same player.
 */

export type EmbedFormat = 'long' | 'short';

/** What the player may do inside the frame: start with sound on a click (full screen comes with
 *  `allowfullscreen`: next to `fullscreen` in `allow` Chrome warns on the other page). */
export const EMBED_ALLOW = 'autoplay; picture-in-picture';
/** Longest start offset taken from `t=` (seconds). */
export const MAX_START_S = 6 * 3600;

export interface EmbedOptions {
  format: EmbedFormat;
  /** Seconds into the video. */
  start: number;
}

/** `?format=short&t=83` → the Short from 1:23; anything unknown → the episode from the start. */
export const parseEmbedQuery = (params: URLSearchParams): EmbedOptions => {
  const t = /^(\d{1,5})s?$/.exec((params.get('t') ?? '').trim());
  const start = t ? Number(t[1]) : 0;
  return { format: params.get('format') === 'short' ? 'short' : 'long', start: start <= MAX_START_S ? start : 0 };
};

/** `/embed/{slug}` with the Short and the start when asked. */
export const embedPath = (slug: string, { format = 'long', start = 0 }: Partial<EmbedOptions> = {}): string => {
  const query = new URLSearchParams();
  if (format === 'short') query.set('format', 'short');
  if (start >= 1) query.set('t', String(Math.floor(start)));
  const search = query.toString();
  return `/embed/${encodeURIComponent(slug)}${search ? `?${search}` : ''}`;
};

const attr = (text: string) => text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** The code for a page elsewhere: a responsive iframe in the video's proportions (as wide as its
 *  column; a Short stays phone-sized), sound and full screen allowed, loaded when scrolled to. */
export const embedCode = (src: string, title: string, format: EmbedFormat): string => {
  const style = format === 'short' ? 'width:100%;max-width:360px;aspect-ratio:9/16;border:0' : 'width:100%;aspect-ratio:16/9;border:0';
  return `<iframe src="${attr(src)}" title="${attr(title)}" style="${style}" allow="${EMBED_ALLOW}" allowfullscreen loading="lazy"></iframe>`;
};

const debaterNames = (participants: Participant[]) => participants.filter((p) => p.role === 'debater' && p.name).map((p) => String(p.name));

/** "{topic} — A vs B": the player's name on the other page (backend embed.embed_title). */
export const embedTitle = (topic: string, participants: Participant[]): string => {
  const text = topic.replace(/\s+/g, ' ').trim() || 'AI debate';
  const versus = debaterNames(participants).join(' vs ');
  return versus ? `${text} — ${versus}` : text;
};

/** The debate's page from the player ("Watch on Debatr"), marked as a visit from an embed. */
export const watchHref = (path: string): string => `${path}${path.includes('?') ? '&' : '?'}ref=embed`;

/** The oEmbed endpoint of a page (its `<link rel="alternate" type="application/json+oembed">`). */
export const oembedHref = (site: string, pageUrl: string): string => `${site.replace(/\/+$/, '')}/api/oembed?url=${encodeURIComponent(pageUrl)}&format=json`;

/** What the player page needs of a debate: its route data stays small (no transcript). */
export interface EmbedDebate {
  id: string;
  slug: string;
  /** The debate's page (canonical path). */
  path: string;
  topic: string;
  /** The show format (`debate`, `rap_battle`: lib/formats). */
  format: string;
  language: string;
  participants: Participant[];
  /** The AI cover shown before the first play (null: the video's first frame in markup). */
  cover: CoverImage | null;
  /** Its audio is ready: the video can play. */
  playable: boolean;
  /** Length of the debate's audio (the episode adds its intro and outro). */
  durationMs: number | null;
}

export const embedDebate = (debate: DebateDetail): EmbedDebate => ({
  id: debate.id,
  slug: debate.slug ?? '',
  path: debate.path ?? `/d/${debate.slug ?? ''}`,
  topic: debate.settings.topic || debate.title || 'AI debate',
  format: debate.settings.format,
  language: debate.settings.language_code || 'en',
  participants: debate.participants,
  cover: debate.cover.current,
  playable: debate.media_status === 'ready',
  durationMs: debate.duration_ms,
});

/** The episode's length as the player counts it (intro + audio + outro); the Short's is known
 *  only from its timeline. */
export const episodeMs = (debate: Pick<EmbedDebate, 'durationMs'>): number | null => (debate.durationMs ? INTRO_MS + debate.durationMs + OUTRO_MS : null);
