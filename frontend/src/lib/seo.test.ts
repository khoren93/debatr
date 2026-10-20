import { describe, expect, it } from 'vitest';
import type { DebateDetail, GalleryItem, MotionPage, Participant, Turn } from '../api/types';
import { galleryFilters } from './gallery';
import { DESCRIPTION_MAX, TITLE_MAX, canonicalRedirect, clip, clipSentences, debateSeo, gallerySeo, homeSeo, jsonLdText, leaderboardSeo, ogLocale, plainText, topicSeo } from './seo';

const SITE = 'https://debatr.example';

const debater = (i: number, name: string): Participant => ({ id: `participant_${i}`, name, role: 'debater', model: `x/${name.toLowerCase()}`, voice_name: null, avatar: null });
const host: Participant = { id: 'participant_0', name: 'The Host', role: 'moderator', model: 'x/host', voice_name: null, avatar: null };

const turn = (seq: number, role: Turn['speaker_role'], text: string, type = 'opening'): Turn => ({
  seq_index: seq,
  round_id: 'round_1',
  turn_type: type,
  speaker_role: role,
  speaker_name: role,
  text,
  error: null,
  model_used: '',
  usage: {} as Turn['usage'],
  created_at: null,
});

const OPENING =
  '**Remote work** wins on focus. [confident] Commutes eat [an hour a day](https://example.com/study) for most workers, and quiet rooms beat open offices for deep work every single time.';

const debate = (over: Partial<DebateDetail> = {}, topic = 'Is remote work better than the office?'): DebateDetail =>
  ({
    id: 'd1',
    slug: 'abc123',
    path: '/d/abc123/is-remote-work-better-than-the-office',
    title: topic,
    status: 'completed',
    is_public: true,
    created_at: '2026-10-18T10:00:00Z',
    published_at: '2026-10-18T11:00:00Z',
    ended_at: '2026-10-18T10:30:00Z',
    settings: { format: 'debate', topic, language: 'English', language_code: 'en' },
    participants: [host, debater(1, 'Claude'), debater(2, 'Gemini')],
    turns: [turn(0, 'moderator', 'Welcome to the debate.', 'moderator_intro'), turn(1, 'debater', OPENING), turn(2, 'debater', 'The office builds trust.'), turn(3, 'moderator', 'Winner: Gemini. Claude was vaguer.', 'verdict')],
    verdict: { winner_id: 'participant_2', winner_name: 'Gemini' },
    motion: null,
    ...over,
  }) as unknown as DebateDetail;

describe('text helpers', () => {
  it('clips between words with an ellipsis', () => {
    expect(clip('Short enough', 20)).toBe('Short enough');
    expect(clip('One two three four five six', 15)).toBe('One two three…');
    expect(clip('Words, then a comma, here', 21)).toBe('Words, then a comma…');
    expect(clip('a'.repeat(30), 10)).toBe(`${'a'.repeat(9)}…`);
  });

  it('ends on a whole sentence when one ends late enough', () => {
    expect(clipSentences('First point is here. Second point goes on and on.', 30)).toBe('First point is here.');
    expect(clipSentences('Tiny. Then a very long sentence that keeps going', 30)).toBe('Tiny. Then a very long…');
    expect(clipSentences('Fits whole.', 30)).toBe('Fits whole.');
  });

  it('turns a speech into plain prose', () => {
    expect(plainText(OPENING)).toBe('Remote work wins on focus. Commutes eat an hour a day for most workers, and quiet rooms beat open offices for deep work every single time.');
    expect(plainText('## Heading\n> quoted\n- item one\n1. item two `code`')).toBe('Heading quoted item one item two code');
  });

  it('keeps JSON-LD from closing its script tag', () => {
    expect(jsonLdText({ name: '</script><b>&' })).toBe('{"name":"\\u003c/script\\u003e\\u003cb\\u003e\\u0026"}');
  });

  it('maps languages to Open Graph locales', () => {
    expect(ogLocale('ru')).toBe('ru_RU');
    expect(ogLocale('en')).toBe('en_US');
    expect(ogLocale('xx')).toBeUndefined();
    expect(ogLocale(undefined)).toBeUndefined();
  });
});

describe('canonicalRedirect', () => {
  const canonical = '/d/abc123/дом-или-офис';

  it('leaves the canonical address alone, encoded or not', () => {
    expect(canonicalRedirect(new URL(`${SITE}/d/abc123/%D0%B4%D0%BE%D0%BC-%D0%B8%D0%BB%D0%B8-%D0%BE%D1%84%D0%B8%D1%81`), canonical)).toBeNull();
  });

  it('sends other spellings to the encoded canonical path with the query', () => {
    expect(canonicalRedirect(new URL(`${SITE}/d/abc123?t=30`), canonical)).toBe('/d/abc123/%D0%B4%D0%BE%D0%BC-%D0%B8%D0%BB%D0%B8-%D0%BE%D1%84%D0%B8%D1%81?t=30');
    expect(canonicalRedirect(new URL(`${SITE}/d/abc123/old-words`), '/d/abc123/new-words')).toBe('/d/abc123/new-words');
    expect(canonicalRedirect(new URL(`${SITE}/d/abc123/%E0%A4%A`), '/d/abc123')).toBe('/d/abc123');
  });
});

describe('debateSeo', () => {
  it('names the topic and the lineup, and invites a vote without the verdict', () => {
    const seo = debateSeo(debate());
    expect(seo.title).toBe('Is remote work better than the office? — Claude vs Gemini');
    expect(seo.description?.startsWith('Remote work wins on focus. Commutes eat an hour a day')).toBe(true);
    expect(seo.description?.endsWith('Watch Claude vs Gemini and vote who won.')).toBe(true);
    expect(seo.description?.length).toBeLessThanOrEqual(DESCRIPTION_MAX);
    expect(seo.description).not.toContain('Winner');
    expect(seo).toMatchObject({ path: '/d/abc123/is-remote-work-better-than-the-office', robots: 'index', type: 'article', lang: 'en', publishedAt: '2026-10-18T11:00:00Z', modifiedAt: '2026-10-18T11:00:00Z' });
    // The preview picture shows the lineup and the question, never the winner.
    expect(seo.image).toMatchObject({ width: 1200, height: 630, alt: 'Claude vs Gemini: Is remote work better than the office?' });
  });

  it('shortens a long topic before it drops the lineup', () => {
    const seo = debateSeo(debate({}, 'Should governments regulate frontier artificial intelligence models before release?'));
    expect(seo.title.length).toBeLessThanOrEqual(TITLE_MAX);
    expect(seo.title).toBe('Should governments regulate frontier… — Claude vs Gemini');
    const crowd = debate({ participants: [host, debater(1, 'Claude'), debater(2, 'Gemini'), debater(3, 'GPT-5.5'), debater(4, 'DeepSeek')] }, 'A topic that is long enough to leave no room for four names');
    expect(debateSeo(crowd).title).toBe('A topic that is long enough to leave no room for four names');
  });

  it('calls a battle a rap battle', () => {
    const battle = debate({ settings: { format: 'rap_battle', topic: 'Cats or dogs?', language: 'English', language_code: 'en' } as DebateDetail['settings'] }, 'Cats or dogs?');
    expect(debateSeo(battle).title).toBe('Cats or dogs? — Claude vs Gemini rap battle');
    const topic = 'Which is the better pet for a small city apartment, cats or dogs?';
    const long = debate({ settings: { format: 'rap_battle', topic, language: 'English', language_code: 'en' } as DebateDetail['settings'] }, topic);
    expect(debateSeo(long).title).toBe('Which is the better pet for a small city… — rap battle');
  });

  it('falls back to the topic when there is no opening yet, and reads the language', () => {
    const seo = debateSeo(debate({ turns: [], settings: { format: 'debate', topic: 'Дом или офис?', language: 'Russian', language_code: 'ru' } as DebateDetail['settings'] }, 'Дом или офис?'));
    expect(seo.description).toBe('Дом или офис? Watch Claude vs Gemini and vote who won.');
    expect(seo.lang).toBe('ru');
  });

  it('describes an Article with its breadcrumbs', () => {
    const motion = { slug: 't1', title: 'Remote work?', versions: 3, items: [], path: '/t/t1/remote-work' };
    const [article, crumbs] = debateSeo(debate({ motion })).jsonLd?.(SITE) ?? [];
    expect(article).toMatchObject({ '@type': 'Article', url: `${SITE}/d/abc123/is-remote-work-better-than-the-office`, inLanguage: 'en', datePublished: '2026-10-18T11:00:00Z', author: { '@type': 'Organization', name: 'Debatr' } });
    expect(article.image).toEqual([expect.stringMatching(new RegExp(`^${SITE}/og/d/abc123\\.png\\?v=`))]);
    expect(JSON.stringify(article)).not.toContain('Winner');
    expect((crumbs.itemListElement as { item: string }[]).map((c) => c.item)).toEqual([`${SITE}/gallery`, `${SITE}/t/t1/remote-work`, `${SITE}/d/abc123/is-remote-work-better-than-the-office`]);
    // A topic with a single version is not a page of its own in the index.
    const [, alone] = debateSeo(debate({ motion: { ...motion, versions: 1 } })).jsonLd?.(SITE) ?? [];
    expect(alone.itemListElement).toHaveLength(2);
  });
});

describe('topicSeo', () => {
  const item = (id: string, names: string[], lang = 'en') => ({ id, slug: id, path: `/d/${id}/x`, topic: 'Cats or dogs?', language_code: lang, participants: names.map((n, i) => debater(i + 1, n)) }) as unknown as GalleryItem;
  const page = (items: GalleryItem[]): MotionPage => ({ slug: 't1', title: 'Cats or dogs?', versions: items.length, items, path: '/t/t1/cats-or-dogs' });

  it('counts the versions and names the models', () => {
    const seo = topicSeo(page([item('a', ['Claude', 'Gemini']), item('b', ['Grok', 'Claude'])]));
    expect(seo.title).toBe('Cats or dogs? — 2 AI debates');
    expect(seo.description).toBe('2 versions of “Cats or dogs?” argued by Claude, Gemini and Grok. Compare the lineups, watch and vote who argued better.');
    expect(seo).toMatchObject({ path: '/t/t1/cats-or-dogs', robots: 'index', lang: 'en' });
    expect(seo.image?.url).toMatch(/^\/og\/t\/t1\.png\?v=/);
    expect(seo.jsonLd?.(SITE)[0].primaryImageOfPage).toMatchObject({ url: expect.stringMatching(new RegExp(`^${SITE}/og/t/t1\\.png`)), width: 1200 });
  });

  it('keeps a single version out of the index and reads a shared language', () => {
    const seo = topicSeo(page([item('a', ['Claude', 'Gemini'], 'ru')]));
    expect(seo.title).toBe('Cats or dogs? — 1 AI debate');
    expect(topicSeo({ ...page([item('a', ['A'])]), title: 'Cats vs dogs' }).title).toBe('Cats vs dogs: 1 AI debate');
    expect(seo.robots).toBe('noindex');
    expect(seo.lang).toBe('ru');
    expect(topicSeo(page([item('a', ['A'], 'ru'), item('b', ['B'], 'de')])).lang).toBe('en');
  });
});

describe('listing pages', () => {
  it('indexes the gallery, its battles and their pages; other filters point at them', () => {
    expect(gallerySeo(galleryFilters(new URLSearchParams()))).toMatchObject({ path: '/gallery', robots: 'index' });
    expect(gallerySeo(galleryFilters(new URLSearchParams('format=rap_battle&page=2')))).toMatchObject({ path: '/gallery?format=rap_battle&page=2', robots: 'index', title: 'AI rap battles — models trade verses · page 2 | Debatr' });
    expect(gallerySeo(galleryFilters(new URLSearchParams('sort=new&category=tech')))).toMatchObject({ path: '/gallery', robots: 'noindex' });
    expect(gallerySeo(galleryFilters(new URLSearchParams('voices=premium')))).toMatchObject({ robots: 'noindex' });
  });

  it('keeps titles and descriptions within the limits', () => {
    for (const seo of [gallerySeo(galleryFilters(new URLSearchParams())), gallerySeo(galleryFilters(new URLSearchParams('format=rap_battle'))), leaderboardSeo('debate'), leaderboardSeo('rap_battle')]) {
      expect(seo.title.length).toBeLessThanOrEqual(TITLE_MAX);
      expect(seo.description?.length ?? 0).toBeGreaterThanOrEqual(100);
      expect(seo.description?.length ?? 0).toBeLessThanOrEqual(DESCRIPTION_MAX);
    }
    expect(leaderboardSeo('rap_battle').path).toBe('/leaderboard?format=rap_battle');
  });

  it("share the site's preview picture", () => {
    for (const seo of [homeSeo(), gallerySeo(galleryFilters(new URLSearchParams())), leaderboardSeo('debate')]) expect(seo.image?.url).toMatch(/^\/og\/site\.png\?v=/);
  });
});
