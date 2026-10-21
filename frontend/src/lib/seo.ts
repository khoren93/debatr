import type { DebateDetail, FormatId, MotionPage, Participant } from '../api/types';
import { APP_DESCRIPTION, APP_NAME, APP_PROFILES, APP_TAGLINE, SEO_COPY } from './brand';
import { DEFAULT_LANGUAGE, type GalleryFilters } from './gallery';
import { SITE_OG_IMAGE, debateOgImage, topicOgImage } from './og';

/**
 * What search engines and link previews read about a page: its title, description, canonical
 * address, robots rule, Open Graph card and JSON-LD. Pure functions (vitest); `<Seo>` renders
 * them into the document's head. Canonical paths of debates and topics come from the API
 * (backend services/seo), never built here. No preview tells who won: the audience votes blind.
 */

export const TITLE_MAX = 60;
export const DESCRIPTION_MAX = 160;
/** Mirrors backend services/seo.TOPIC_INDEX_MIN_VERSIONS: a topic with one version is a thin
 *  copy of that debate's page, so it stays out of the index. */
export const TOPIC_INDEX_MIN_VERSIONS = 2;
const BRAND_SUFFIX = ` | ${APP_NAME}`;

/** `index`: public pages; `noindex`: listed nowhere but links are followed (filtered views,
 *  error pages, thin topics); `private`: pages of an account. */
export type Robots = 'index' | 'noindex' | 'private';

export const ROBOTS: Record<Robots, string> = {
  index: 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1',
  noindex: 'noindex, follow',
  private: 'noindex, nofollow',
};

export interface SeoImage {
  /** Absolute, or a path on the site (lib/og.ts): `<Seo>` makes it absolute. */
  url: string;
  width: number;
  height: number;
  alt: string;
  type?: string;
}

export type JsonLd = Record<string, unknown>;

/** A route module's `handle`: the language of its page (`<html lang>`, root.tsx); `framed`: a
 *  page for other sites' iframes (no scroll restoration: nothing scrolls, and WebKit keeps
 *  `history.state` empty in a third-party frame, which React Router's script trips over). */
export interface PageHandle<LoaderData = unknown> {
  lang?: (loaderData: LoaderData) => string | undefined;
  framed?: boolean;
}

export interface SeoData {
  title: string;
  description?: string;
  /** Canonical path (and query) on the site, e.g. `/gallery?format=rap_battle`; pages without
   *  one get neither a canonical link nor an Open Graph card. */
  path?: string;
  robots: Robots;
  type?: 'website' | 'article';
  image?: SeoImage | null;
  /** BCP 47 code of the page's language (`og:locale`). */
  lang?: string;
  publishedAt?: string | null;
  modifiedAt?: string | null;
  /** JSON-LD objects; absolute URLs are filled in by `jsonLd(site)`. */
  jsonLd?: (site: string) => JsonLd[];
  /** The page has a player for other sites: name its oEmbed endpoint (backend routes_oembed). */
  oembed?: boolean;
}

// --- text ---------------------------------------------------------------------------------------

export const collapse = (text: string) => text.replace(/\s+/g, ' ').trim();

/** `text` cut to `max` characters between words, with an ellipsis. */
export const clip = (text: string, max: number): string => {
  const flat = collapse(text);
  if (flat.length <= max) return flat;
  let cut = flat.slice(0, max - 1);
  const space = cut.lastIndexOf(' ');
  // Mid-word: back to the last space (unless that loses too much of the text).
  if (flat[max - 1] !== ' ' && space >= max * 0.6) cut = cut.slice(0, space);
  return `${cut.replace(/[\s,;:.!?—–-]+$/u, '')}…`;
};

/** Up to `max` characters ending with a whole sentence when one ends late enough, else `clip`. */
export const clipSentences = (text: string, max: number): string => {
  const flat = collapse(text);
  if (flat.length <= max) return flat;
  const head = flat.slice(0, max);
  let end = -1;
  for (const match of head.matchAll(/[.!?…](?=\s|$)/gu)) end = match.index + 1;
  return end >= max * 0.55 ? head.slice(0, end) : clip(flat, max);
};

/** A turn's speech as plain prose: no Markdown, no `[emotion]` / studio tags. */
export const plainText = (text: string): string =>
  collapse(
    text
      .replace(/!?\[([^\]\n]*)\]\([^)\n]*\)/g, '$1') // links and images: their text
      .replace(/\[[^\]\n]{1,80}\]/g, ' ') // [laughs], [visual: …], [dispute 2: …]
      .replace(/^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)/gm, '') // headings, quotes, lists
      .replace(/(\*\*|__|~~|`+|\*|_(?=\S)|(?<=\S)_)/g, '') // emphasis and code marks
      .replace(/\s+([,.;:!?])/g, '$1'),
  );

export const canonicalUrl = (site: string, path: string) => `${site.replace(/\/+$/, '')}${path}`;

/** Where to send a visitor who asked for another spelling of a page whose canonical path is
 *  `canonical` (no or an old kebab, a merged topic): the encoded path with the query kept; null
 *  when the address is already the canonical one. */
export const canonicalRedirect = (url: URL, canonical: string): string | null => {
  let current = url.pathname;
  try {
    current = decodeURIComponent(current);
  } catch {
    // A malformed escape is not the canonical spelling either.
  }
  return current === canonical ? null : `${encodeURI(canonical)}${url.search}`;
};

const LOCALES: Record<string, string> = {
  en: 'en_US',
  ru: 'ru_RU',
  es: 'es_ES',
  fr: 'fr_FR',
  de: 'de_DE',
  zh: 'zh_CN',
  it: 'it_IT',
  pt: 'pt_BR',
  ja: 'ja_JP',
  ko: 'ko_KR',
  hy: 'hy_AM',
  uk: 'uk_UA',
  pl: 'pl_PL',
  tr: 'tr_TR',
  ar: 'ar_AR',
  hi: 'hi_IN',
  nl: 'nl_NL',
};

/** `og:locale` of a language code (Facebook's language_TERRITORY form); undefined if unknown. */
export const ogLocale = (code: string | undefined) => (code ? LOCALES[code.toLowerCase().slice(0, 2)] : undefined);

/** JSON for a `<script type="application/ld+json">`: nothing in it can close the tag. */
export const jsonLdText = (data: JsonLd) =>
  JSON.stringify(data)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');

const withBrand = (title: string) => (title.length + BRAND_SUFFIX.length <= TITLE_MAX ? `${title}${BRAND_SUFFIX}` : clip(title, TITLE_MAX));

/** `{topic}{suffix}` within TITLE_MAX: the topic gives way first, unless too little of it would
 *  be left, then the suffix goes. */
const titleWith = (topic: string, suffixes: string[]): string => {
  for (const suffix of suffixes) if (topic.length + suffix.length <= TITLE_MAX) return `${topic}${suffix}`;
  const shortest = suffixes.at(-1) ?? '';
  const room = TITLE_MAX - shortest.length;
  return room >= 30 ? `${clip(topic, room)}${shortest}` : clip(topic, TITLE_MAX);
};

const joinNames = (names: string[]) => (names.length <= 2 ? names.join(' and ') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`);

// --- JSON-LD pieces -----------------------------------------------------------------------------

const organization = (site: string): JsonLd => ({
  '@type': 'Organization',
  '@id': `${site}/#organization`,
  name: APP_NAME,
  url: `${site}/`,
  logo: { '@type': 'ImageObject', url: `${site}/favicon.svg` },
});

export const breadcrumbs = (site: string, items: { name: string; path: string }[]): JsonLd => ({
  '@context': 'https://schema.org',
  '@type': 'BreadcrumbList',
  itemListElement: items.map((item, i) => ({ '@type': 'ListItem', position: i + 1, name: item.name, item: canonicalUrl(site, item.path) })),
});

// --- pages --------------------------------------------------------------------------------------

export const homeSeo = (): SeoData => ({
  title: `${APP_NAME} — ${APP_TAGLINE}`,
  description: APP_DESCRIPTION,
  path: '/',
  robots: 'index',
  type: 'website',
  image: SITE_OG_IMAGE,
  lang: 'en',
  jsonLd: (site) => [
    {
      '@context': 'https://schema.org',
      '@type': 'WebSite',
      '@id': `${site}/#website`,
      name: APP_NAME,
      alternateName: `${APP_NAME} — ${APP_TAGLINE}`,
      url: `${site}/`,
      description: APP_DESCRIPTION,
      inLanguage: 'en',
      publisher: { '@id': `${site}/#organization` },
    },
    { '@context': 'https://schema.org', ...organization(site), description: APP_DESCRIPTION, sameAs: APP_PROFILES },
  ],
});

/** Indexed: the gallery (English debates), its rap-battle view and their pages; every other
 *  filter, another language included, is a view (noindex, follow) that points at the plain list. */
export const gallerySeo = (filters: GalleryFilters): SeoData => {
  const battles = filters.format === 'rap_battle';
  const copy = battles ? SEO_COPY.galleryBattles : SEO_COPY.gallery;
  const query = new URLSearchParams();
  if (filters.format !== 'all') query.set('format', filters.format);
  if (filters.page > 1) query.set('page', String(filters.page));
  const search = query.toString();
  const filtered = filters.sort !== 'trending' || filters.language !== DEFAULT_LANGUAGE || filters.category !== 'all' || !!filters.model || filters.premium;
  const title = filters.page > 1 ? `${copy.title} · page ${filters.page}` : copy.title;
  return { title: withBrand(title), description: copy.description, path: `/gallery${search ? `?${search}` : ''}`, robots: filtered ? 'noindex' : 'index', type: 'website', image: SITE_OG_IMAGE, lang: 'en' };
};

export const leaderboardSeo = (format: FormatId): SeoData => {
  const copy = format === 'rap_battle' ? SEO_COPY.leaderboardBattles : SEO_COPY.leaderboard;
  return { title: withBrand(copy.title), description: copy.description, path: format === 'rap_battle' ? '/leaderboard?format=rap_battle' : '/leaderboard', robots: 'index', type: 'website', image: SITE_OG_IMAGE, lang: 'en' };
};

const debaterNames = (participants: Participant[]) => participants.filter((p) => p.role === 'debater' && p.name).map((p) => String(p.name));

/** `/d/…`: "{topic} — A vs B" (a battle: "… — A vs B rap battle"), the opening argument and a
 *  call to vote; an Article with the breadcrumbs Gallery › topic › debate. */
export const debateSeo = (debate: DebateDetail): SeoData => {
  const topic = collapse(debate.settings.topic || debate.title || 'AI debate');
  const battle = debate.settings.format === 'rap_battle';
  const versus = debaterNames(debate.participants).join(' vs ');
  // "A vs B" tells the versions of a topic apart: the topic is shortened for it first.
  const suffixes = battle ? [...(versus ? [` — ${versus} rap battle`] : []), ' — rap battle'] : [versus ? ` — ${versus}` : ''];
  const title = titleWith(topic, suffixes);

  const call = versus ? `Watch ${versus} and vote who won.` : 'Watch the AI debate and vote who won.';
  const opening = debate.turns.find((t) => t.speaker_role === 'debater' && !t.error && t.text.trim());
  const room = DESCRIPTION_MAX - call.length - 1;
  const lead = opening ? plainText(opening.text) : '';
  const description = lead.length >= 40 && room >= 40 ? `${clipSentences(lead, room)} ${call}` : clip(`${topic} ${call}`, DESCRIPTION_MAX);

  const path = debate.path ?? `/d/${debate.slug}`;
  const lang = debate.settings.language_code || 'en';
  const published = debate.published_at ?? debate.created_at;
  const modified = [debate.published_at, debate.ended_at].filter((d): d is string => !!d).sort().at(-1) ?? published;
  const motion = debate.motion && debate.motion.versions >= TOPIC_INDEX_MIN_VERSIONS ? debate.motion : null;
  const image = debateOgImage(debate);
  return {
    title,
    description,
    path,
    robots: 'index',
    type: 'article',
    image,
    lang,
    publishedAt: published,
    modifiedAt: modified,
    oembed: true,
    jsonLd: (site) => [
      {
        '@context': 'https://schema.org',
        '@type': 'Article',
        headline: clip(topic, 110),
        description,
        url: canonicalUrl(site, path),
        mainEntityOfPage: canonicalUrl(site, path),
        inLanguage: lang,
        datePublished: published,
        dateModified: modified,
        ...(image ? { image: [canonicalUrl(site, image.url)] } : {}),
        author: organization(site),
        publisher: organization(site),
        ...(versus ? { about: debaterNames(debate.participants).map((name) => ({ '@type': 'Thing', name })) } : {}),
      },
      breadcrumbs(site, [{ name: 'Gallery', path: '/gallery' }, ...(motion ? [{ name: clip(motion.title, 80), path: motion.path }] : []), { name: clip(topic, 80), path }]),
    ],
  };
};

/** `/t/…`: "{topic}: N AI debates" ("{question}? — N AI debates"); indexed from
 *  TOPIC_INDEX_MIN_VERSIONS versions. */
export const topicSeo = (page: MotionPage): SeoData => {
  const topic = collapse(page.title || 'AI debate');
  const count = page.versions === 1 ? '1 AI debate' : `${page.versions} AI debates`;
  const title = titleWith(topic, [`${/[?!.…]$/u.test(topic) ? ' —' : ':'} ${count}`]);
  const names = [...new Set(page.items.flatMap((item) => debaterNames(item.participants)))].slice(0, 4);
  const who = names.length ? ` by ${joinNames(names)}` : '';
  const description = clip(`${page.versions === 1 ? 'One version' : `${page.versions} versions`} of “${topic}” argued${who}. Compare the lineups, watch and vote who argued better.`, DESCRIPTION_MAX);
  const languages = new Set(page.items.map((item) => item.language_code));
  const lang = languages.size === 1 ? [...languages][0] : 'en';
  const image = topicOgImage(page);
  return {
    title,
    description,
    path: page.path,
    robots: page.versions >= TOPIC_INDEX_MIN_VERSIONS ? 'index' : 'noindex',
    type: 'website',
    image,
    lang,
    oembed: true,
    jsonLd: (site) => [
      {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        name: topic,
        description,
        url: canonicalUrl(site, page.path),
        primaryImageOfPage: { '@type': 'ImageObject', url: canonicalUrl(site, image.url), width: image.width, height: image.height },
        inLanguage: lang,
        isPartOf: { '@type': 'WebSite', name: APP_NAME, url: `${site}/` },
        mainEntity: {
          '@type': 'ItemList',
          numberOfItems: page.versions,
          itemListElement: page.items.map((item, i) => ({ '@type': 'ListItem', position: i + 1, url: canonicalUrl(site, item.path), name: clip(`${item.topic} — ${debaterNames(item.participants).join(' vs ')}`, 110) })),
        },
      },
      breadcrumbs(site, [
        { name: 'Gallery', path: '/gallery' },
        { name: clip(topic, 80), path: page.path },
      ]),
    ],
  };
};

/** The player of another site's iframe (`/embed/…`): a title for the frame, out of every index
 *  (the debate's own page is the one to find; `X-Robots-Tag` says so as well). */
export const embedSeo = (title: string): SeoData => ({ title: withBrand(collapse(title)), robots: 'noindex' });

/** Pages of an account and the sign-in forms: a title, kept out of every index. */
/** The privacy notice: indexed, outside the sitemaps. */
export const privacySeo = (): SeoData => ({
  title: withBrand('Privacy'),
  description: `What ${APP_NAME} keeps about accounts and visits, why, and for how long.`,
  path: '/privacy',
  robots: 'index',
  type: 'website',
  image: SITE_OG_IMAGE,
  lang: 'en',
});

export const privateSeo = (title: string): SeoData => ({ title: title ? withBrand(title) : APP_NAME, robots: 'private' });

/** Error pages: the status says it all to crawlers; people get a title. */
const ERROR_TITLES: Record<number, string> = { 404: 'Page not found', 410: 'Page removed', 403: 'Private page' };
export const errorSeo = (status: number): SeoData => ({ title: withBrand(ERROR_TITLES[status] ?? 'Something went wrong'), robots: 'noindex' });
