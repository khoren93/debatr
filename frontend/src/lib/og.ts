import type { DebateDetail, MotionPage, Participant } from '../api/types';
import { APP_TAGLINE, SEO_COPY } from './brand';
import { debaterColor, shortModelName } from './format';
import { formatSpec } from './formats';
import type { SeoImage } from './seo';

/**
 * Link previews (Open Graph / X cards): a 1200×630 picture of every public page, drawn by the
 * SSR server (`src/server/og`, routes `og/*`) from the card data built here. Pure (vitest): the
 * page and the image route build the same card, so the page's `?v=` names exactly the picture the
 * route draws, and social networks fetch a new one when it changes. Like the gallery cover, the
 * card shows the lineup and the question, never the winner (blind voting).
 */

export const OG_WIDTH = 1200;
export const OG_HEIGHT = 630;
/** Bump with every change of the card's look: every preview URL (`?v=`) changes with it. */
export const OG_DESIGN = 1;
/** Longer headlines are cut for the picture (debates from before TOPIC_MAX_LENGTH hold 500). */
export const OG_TEXT_MAX = 160;
/** Sides drawn at most (the gallery cover's rule). */
const MAX_SIDES = 4;

export interface OgSide {
  name: string;
  /** OpenRouter model id: its author picks the logo. */
  model: string;
  color: string;
}

export interface OgCard {
  /** The headline: a debate's question, a topic's title or the site's line. */
  text: string;
  /** The chip in the top-right corner ("AI DEBATE", "RAP BATTLE", "3 VERSIONS"). */
  badge: string;
  sides: OgSide[];
  /** BCP 47 language of `text` (picks the font of Han characters: Chinese, Japanese, Korean). */
  lang: string;
}

const collapse = (text: string) => text.replace(/\s+/g, ' ').trim();

/** `text` within OG_TEXT_MAX characters, cut between words with an ellipsis. */
export const ogText = (text: string): string => {
  const flat = collapse(text);
  const chars = [...flat];
  if (chars.length <= OG_TEXT_MAX) return flat;
  const cut = chars.slice(0, OG_TEXT_MAX - 1).join('');
  const space = cut.lastIndexOf(' ');
  return `${(space >= OG_TEXT_MAX * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,;:.!?—–-]+$/u, '')}…`;
};

const sideOf = (p: Participant, i: number): OgSide => ({ name: p.name?.trim() || shortModelName(p.model) || 'Debater', model: p.model, color: debaterColor(i) });

const debaters = (participants: Participant[]) => participants.filter((p) => p.role !== 'moderator');

export const debateCard = (debate: Pick<DebateDetail, 'title' | 'settings' | 'participants'>): OgCard => ({
  text: ogText(debate.settings.topic || debate.title || 'AI debate'),
  badge: formatSpec(debate.settings.format).label,
  sides: debaters(debate.participants).slice(0, MAX_SIDES).map(sideOf),
  lang: debate.settings.language_code || 'en',
});

/** A topic: its title over the models that argued it across the public versions (the first
 *  debater of each model, in the versions' order), and how many versions there are. */
export const topicCard = (page: Pick<MotionPage, 'title' | 'versions' | 'items'>): OgCard => {
  const seen = new Map<string, Participant>();
  for (const item of page.items) for (const p of debaters(item.participants)) if (!seen.has(p.model)) seen.set(p.model, p);
  const languages = new Set(page.items.map((item) => item.language_code));
  return {
    text: ogText(page.title || 'AI debate'),
    badge: page.versions === 1 ? formatSpec(page.items[0]?.format).label : `${page.versions} VERSIONS`,
    sides: [...seen.values()].slice(0, MAX_SIDES).map(sideOf),
    lang: languages.size === 1 ? [...languages][0] : 'en',
  };
};

/** Home, gallery and ranking: the site's line over the flagship families. */
export const SITE_CARD: OgCard = {
  text: SEO_COPY.card,
  badge: APP_TAGLINE.toUpperCase(),
  sides: [
    { name: 'Claude', model: 'anthropic/claude', color: debaterColor(0) },
    { name: 'GPT', model: 'openai/gpt', color: debaterColor(1) },
    { name: 'Gemini', model: 'google/gemini', color: debaterColor(2) },
    { name: 'Grok', model: 'x-ai/grok', color: debaterColor(3) },
  ],
  lang: 'en',
};

/** cyrb53: a 53-bit string hash, pure JS (the browser renders `<Seo>` too). */
const hash53 = (text: string): number => {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return 4294967296 * (2097151 & h2) + (h1 >>> 0);
};

/** The card's version for its URL (`?v=`): changes with its data and with OG_DESIGN. */
export const ogVersion = (card: OgCard): string => hash53(JSON.stringify([OG_DESIGN, card])).toString(36);

/** Words for screen readers and crawlers: who argues what (never who won). */
export const ogAlt = (card: OgCard): string => {
  const lineup = card.sides.map((s) => s.name).join(' vs ');
  return [lineup, card.text].filter(Boolean).join(': ').slice(0, 420);
};

const image = (path: string, card: OgCard): SeoImage => ({ url: `${path}?v=${ogVersion(card)}`, width: OG_WIDTH, height: OG_HEIGHT, alt: ogAlt(card) });

/** Image routes (src/routes/og.*): the slug's `.png` file. */
export const OG_PATHS = {
  debate: (slug: string) => `/og/d/${encodeURIComponent(slug)}.png`,
  topic: (slug: string) => `/og/t/${encodeURIComponent(slug)}.png`,
  site: '/og/site.png',
} as const;

export const debateOgImage = (debate: Pick<DebateDetail, 'slug' | 'title' | 'settings' | 'participants'>): SeoImage | null =>
  debate.slug ? image(OG_PATHS.debate(debate.slug), debateCard(debate)) : null;

export const topicOgImage = (page: Pick<MotionPage, 'slug' | 'title' | 'versions' | 'items'>): SeoImage => image(OG_PATHS.topic(page.slug), topicCard(page));

export const SITE_OG_IMAGE: SeoImage = image(OG_PATHS.site, SITE_CARD);
