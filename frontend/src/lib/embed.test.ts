import { describe, expect, it } from 'vitest';
import type { DebateDetail, Participant } from '../api/types';
import { INTRO_MS, OUTRO_MS } from '../video/constants';
import { EMBED_ALLOW, MAX_START_S, embedCode, embedDebate, embedPath, embedTitle, episodeMs, oembedHref, parseEmbedQuery, watchHref } from './embed';

const person = (name: string | null, role = 'debater'): Participant => ({ name, role, model: 'x/y', voice_name: null, avatar: null });

describe('parseEmbedQuery', () => {
  const parse = (search: string) => parseEmbedQuery(new URLSearchParams(search));

  it('reads the Short and the start in seconds', () => {
    expect(parse('')).toEqual({ format: 'long', start: 0 });
    expect(parse('format=short&t=83')).toEqual({ format: 'short', start: 83 });
    expect(parse('t=12s')).toEqual({ format: 'long', start: 12 });
  });

  it('ignores what it does not know', () => {
    expect(parse('format=square&t=1m23s')).toEqual({ format: 'long', start: 0 });
    expect(parse('t=-5')).toEqual({ format: 'long', start: 0 });
    expect(parse(`t=${MAX_START_S + 1}`)).toEqual({ format: 'long', start: 0 });
  });
});

describe('embedPath', () => {
  it('adds only what differs from the defaults', () => {
    expect(embedPath('abc123')).toBe('/embed/abc123');
    expect(embedPath('abc123', { format: 'short' })).toBe('/embed/abc123?format=short');
    expect(embedPath('abc123', { start: 83.7 })).toBe('/embed/abc123?t=83');
    expect(embedPath('abc123', { format: 'short', start: 5 })).toBe('/embed/abc123?format=short&t=5');
    expect(embedPath('abc123', { start: 0.4 })).toBe('/embed/abc123');
  });

  it('round-trips through the query parser', () => {
    const path = embedPath('abc123', { format: 'short', start: 42 });
    expect(parseEmbedQuery(new URL(path, 'https://x.example').searchParams)).toEqual({ format: 'short', start: 42 });
  });
});

describe('embedCode', () => {
  it('is a responsive iframe with sound and full screen', () => {
    const code = embedCode('https://debatr.example/embed/abc?format=short&t=3', 'Is "AI" <b>safe</b>?', 'short');
    const frame = new DOMParserLike(code);
    expect(frame.tag).toBe('iframe');
    expect(frame.attrs.src).toBe('https://debatr.example/embed/abc?format=short&amp;t=3');
    expect(frame.attrs.title).toBe('Is &quot;AI&quot; &lt;b&gt;safe&lt;/b&gt;?');
    expect(frame.attrs.style).toBe('width:100%;max-width:360px;aspect-ratio:9/16;border:0');
    expect(frame.attrs.allow).toBe(EMBED_ALLOW);
    expect(code).toContain(' allowfullscreen ');
    expect(code).toContain('loading="lazy"');
    expect(embedCode('https://debatr.example/embed/abc', 'T', 'long')).toContain('style="width:100%;aspect-ratio:16/9;border:0"');
  });
});

/** The attributes of a single tag, as written (no entity decoding). */
class DOMParserLike {
  tag: string;
  attrs: Record<string, string>;
  constructor(html: string) {
    const open = /^<(\w+)([^>]*)>/.exec(html);
    this.tag = open?.[1] ?? '';
    this.attrs = Object.fromEntries([...(open?.[2] ?? '').matchAll(/(\w[\w-]*)="([^"]*)"/g)].map((m) => [m[1], m[2]]));
  }
}

describe('titles and links', () => {
  it('names the player after the topic and the debaters', () => {
    expect(embedTitle('  Tabs or\nspaces? ', [person('The Host', 'moderator'), person('Claude'), person('GPT-5.5')])).toBe('Tabs or spaces? — Claude vs GPT-5.5');
    expect(embedTitle('Tabs?', [person(null)])).toBe('Tabs?');
    expect(embedTitle('', [])).toBe('AI debate');
  });

  it('marks visits from the player and builds the oEmbed address', () => {
    expect(watchHref('/d/abc/tabs')).toBe('/d/abc/tabs?ref=embed');
    expect(watchHref('/d/abc?x=1')).toBe('/d/abc?x=1&ref=embed');
    expect(oembedHref('https://debatr.example/', 'https://debatr.example/d/abc/лучше')).toBe('https://debatr.example/api/oembed?url=https%3A%2F%2Fdebatr.example%2Fd%2Fabc%2F%D0%BB%D1%83%D1%87%D1%88%D0%B5&format=json');
  });
});

describe('embedDebate', () => {
  const detail = {
    id: 'id-1',
    slug: 'abc123',
    path: '/d/abc123/cats-or-dogs',
    title: 'Cats or dogs',
    settings: { topic: 'Cats or dogs?', format: 'rap_battle', language_code: 'ru' },
    participants: [person('Claude')],
    cover: { current: null },
    media_status: 'ready',
    duration_ms: 60_000,
    turns: [{ text: 'a long transcript' }],
  } as unknown as DebateDetail;

  it('keeps what the player needs and nothing of the transcript', () => {
    const data = embedDebate(detail);
    expect(data).toEqual({
      id: 'id-1',
      slug: 'abc123',
      path: '/d/abc123/cats-or-dogs',
      topic: 'Cats or dogs?',
      format: 'rap_battle',
      language: 'ru',
      participants: [person('Claude')],
      cover: null,
      playable: true,
      durationMs: 60_000,
    });
    expect(JSON.stringify(data)).not.toContain('transcript');
    expect(embedDebate({ ...detail, media_status: 'running' } as DebateDetail).playable).toBe(false);
  });

  it('counts the episode with its intro and outro', () => {
    expect(episodeMs({ durationMs: 60_000 })).toBe(INTRO_MS + 60_000 + OUTRO_MS);
    expect(episodeMs({ durationMs: null })).toBeNull();
  });
});
