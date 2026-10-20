import { describe, expect, it } from 'vitest';
import { galleryFilters, galleryPath } from './gallery';

describe('galleryFilters', () => {
  it('falls back to the defaults for missing or unknown values', () => {
    expect(galleryFilters(new URLSearchParams('sort=hot&format=opera&category=x'))).toEqual({ sort: 'trending', period: 'all', format: 'all', category: 'all', model: null, premium: false });
  });

  it('reads every filter of the URL', () => {
    expect(galleryFilters(new URLSearchParams('sort=top&period=week&format=rap_battle&category=tech&model=%20openai/gpt-5.5%20&voices=premium'))).toEqual({
      sort: 'top',
      period: 'week',
      format: 'rap_battle',
      category: 'tech',
      model: 'openai/gpt-5.5',
      premium: true,
    });
  });
});

describe('galleryPath', () => {
  it('asks for one card per topic and leaves the defaults out', () => {
    expect(galleryPath(galleryFilters(new URLSearchParams()))).toBe('/gallery?sort=trending&group=motion');
  });

  it('sends the period only with sort=top', () => {
    expect(galleryPath(galleryFilters(new URLSearchParams('sort=new&period=week')))).toBe('/gallery?sort=new&group=motion');
    expect(galleryPath(galleryFilters(new URLSearchParams('sort=top&period=week&voices=premium&category=fun')))).toBe('/gallery?category=fun&sort=top&period=week&premium_voices=true&group=motion');
  });
});
