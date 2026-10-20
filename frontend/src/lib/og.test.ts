import { describe, expect, it } from 'vitest';
import type { DebateDetail, GalleryItem, MotionPage, Participant } from '../api/types';
import { DEBATER_COLORS } from './format';
import { OG_HEIGHT, OG_TEXT_MAX, OG_WIDTH, SITE_OG_IMAGE, debateCard, debateOgImage, ogAlt, ogText, ogVersion, topicCard, topicOgImage } from './og';

const person = (name: string | null, model: string, role = 'debater'): Participant => ({ name, role, model, voice_name: null, avatar: null });
const host = person('The Host', 'x/host', 'moderator');

const debate = (topic: string, participants: Participant[], over: Partial<DebateDetail['settings']> = {}) =>
  ({ slug: 'abc123', title: topic, settings: { format: 'debate', topic, language_code: 'en', ...over }, participants }) as unknown as DebateDetail;

describe('debateCard', () => {
  it('puts the question over the debaters in their speaker colours, without the host', () => {
    const card = debateCard(debate('Cats or dogs?', [host, person('Claude', 'anthropic/claude-opus-5.5'), person('Gemini', 'google/gemini-3.5-pro')]));
    expect(card).toEqual({
      text: 'Cats or dogs?',
      badge: 'AI DEBATE',
      sides: [
        { name: 'Claude', model: 'anthropic/claude-opus-5.5', color: DEBATER_COLORS[0] },
        { name: 'Gemini', model: 'google/gemini-3.5-pro', color: DEBATER_COLORS[1] },
      ],
      lang: 'en',
    });
  });

  it('names a battle, falls back to the model name and draws at most four sides', () => {
    const battle = debateCard(debate('Cats or dogs?', [host, person(null, 'openai/gpt-5.5'), person('Grok', 'x-ai/grok-5')], { format: 'rap_battle', language_code: 'ru' }));
    expect(battle.badge).toBe('RAP BATTLE');
    expect(battle.sides[0].name).toBe('gpt 5.5');
    expect(battle.lang).toBe('ru');
    const crowd = debateCard(debate('Five?', [host, ...['a', 'b', 'c', 'd', 'e'].map((n) => person(n, `x/${n}`))]));
    expect(crowd.sides.map((s) => s.name)).toEqual(['a', 'b', 'c', 'd']);
  });

  it('cuts long questions between words', () => {
    const long = Array.from({ length: 60 }, (_, i) => `word${i}`).join(' ');
    const text = ogText(long);
    expect([...text].length).toBeLessThanOrEqual(OG_TEXT_MAX);
    expect(text.endsWith('…')).toBe(true);
    expect(text).toMatch(/ word\d+…$/);
    expect(ogText('  Short   question? ')).toBe('Short question?');
  });
});

describe('topicCard', () => {
  const item = (models: string[], lang = 'en', format = 'debate') => ({ format, language_code: lang, participants: [host, ...models.map((m) => person(m.split('/')[1], m))] }) as unknown as GalleryItem;
  const page = (items: GalleryItem[]): MotionPage => ({ slug: 't1', title: 'Cats or dogs?', versions: items.length, items, path: '/t/t1/cats-or-dogs' });

  it('shows the models of every version once and how many versions there are', () => {
    const card = topicCard(page([item(['a/claude', 'b/gemini']), item(['c/grok', 'a/claude']), item(['d/qwen', 'e/kimi'])]));
    expect(card.sides.map((s) => s.model)).toEqual(['a/claude', 'b/gemini', 'c/grok', 'd/qwen']);
    expect(card.sides.map((s) => s.color)).toEqual(DEBATER_COLORS.slice(0, 4));
    expect(card.badge).toBe('3 VERSIONS');
  });

  it('calls a single version by its format and keeps a shared language', () => {
    expect(topicCard(page([item(['a/x', 'b/y'], 'ja', 'rap_battle')]))).toMatchObject({ badge: 'RAP BATTLE', lang: 'ja' });
    expect(topicCard(page([item(['a/x'], 'ja'), item(['b/y'], 'ko')])).lang).toBe('en');
  });
});

describe('preview images', () => {
  const card = () => debate('Cats or dogs?', [host, person('Claude', 'anthropic/claude'), person('Gemini', 'google/gemini')]);

  it('names the picture of a debate by its version, which follows the data', () => {
    const image = debateOgImage(card());
    expect(image).toMatchObject({ width: OG_WIDTH, height: OG_HEIGHT, alt: 'Claude vs Gemini: Cats or dogs?' });
    expect(image?.url).toMatch(/^\/og\/d\/abc123\.png\?v=[0-9a-z]+$/);
    expect(debateOgImage(card())?.url).toBe(image?.url);
    expect(debateOgImage(debate('Cats or dogs!', card().participants))?.url).not.toBe(image?.url);
    expect(debateOgImage({ ...card(), slug: null })).toBeNull();
  });

  it('has pictures for topics and the site', () => {
    const page: MotionPage = { slug: 'tp', title: 'Cats?', versions: 1, items: [], path: '/t/tp/cats' };
    expect(topicOgImage(page).url).toMatch(/^\/og\/t\/tp\.png\?v=/);
    expect(SITE_OG_IMAGE.url).toMatch(/^\/og\/site\.png\?v=/);
  });

  it('keeps the version stable and the alt text short', () => {
    const c = debateCard(card());
    expect(ogVersion(c)).toBe(ogVersion(structuredClone(c)));
    expect(ogAlt({ ...c, text: 'x'.repeat(600) }).length).toBeLessThanOrEqual(420);
  });
});
