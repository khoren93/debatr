import { describe, expect, it } from 'vitest';
import { GALLERY_MAX_PAGE, galleryFilters, galleryHref, galleryPath, orderOf, orderParams } from './gallery';

describe('galleryFilters', () => {
  it('falls back to the defaults for missing or unknown values', () => {
    expect(galleryFilters(new URLSearchParams('sort=hot&format=opera&lang=russian&category=x&page=abc'))).toEqual({ sort: 'trending', period: 'all', format: 'all', language: 'en', category: 'all', model: null, premium: false, page: 1 });
  });

  it('shows English unless the URL names another language or all of them', () => {
    expect(galleryFilters(new URLSearchParams()).language).toBe('en');
    expect(galleryFilters(new URLSearchParams('lang=RU')).language).toBe('ru');
    expect(galleryFilters(new URLSearchParams('lang=all')).language).toBe('all');
  });

  it('reads every filter of the URL', () => {
    expect(galleryFilters(new URLSearchParams('sort=top&period=week&format=rap_battle&lang=hy&category=tech&model=%20openai/gpt-5.5%20&voices=premium&page=3'))).toEqual({
      sort: 'top',
      period: 'week',
      format: 'rap_battle',
      language: 'hy',
      category: 'tech',
      model: 'openai/gpt-5.5',
      premium: true,
      page: 3,
    });
  });

  it('keeps the page a whole number in range', () => {
    expect(galleryFilters(new URLSearchParams('page=0')).page).toBe(1);
    expect(galleryFilters(new URLSearchParams('page=-2')).page).toBe(1);
    expect(galleryFilters(new URLSearchParams('page=2.5')).page).toBe(1);
    expect(galleryFilters(new URLSearchParams('page=99999')).page).toBe(GALLERY_MAX_PAGE);
  });
});

describe('galleryPath', () => {
  it('asks for one card per topic in English by default', () => {
    expect(galleryPath(galleryFilters(new URLSearchParams()))).toBe('/gallery?sort=trending&language=en&group=motion&limit=24');
    expect(galleryPath(galleryFilters(new URLSearchParams('lang=all')))).toBe('/gallery?sort=trending&group=motion&limit=24');
    expect(galleryPath(galleryFilters(new URLSearchParams('lang=ru&format=rap_battle')))).toBe('/gallery?sort=trending&format=rap_battle&language=ru&group=motion&limit=24');
  });

  it('sends the period only with sort=top', () => {
    expect(galleryPath(galleryFilters(new URLSearchParams('sort=new&period=week')))).toBe('/gallery?sort=new&language=en&group=motion&limit=24');
    expect(galleryPath(galleryFilters(new URLSearchParams('sort=top&period=week&voices=premium&category=fun')))).toBe('/gallery?category=fun&sort=top&period=week&premium_voices=true&language=en&group=motion&limit=24');
  });

  it('pages with an offset', () => {
    expect(galleryPath(galleryFilters(new URLSearchParams('page=3')))).toBe('/gallery?sort=trending&language=en&group=motion&limit=24&offset=48');
  });
});

describe('galleryHref', () => {
  it('is the page address with the defaults left out', () => {
    expect(galleryHref(galleryFilters(new URLSearchParams()))).toBe('/gallery');
    expect(galleryHref({ ...galleryFilters(new URLSearchParams('format=rap_battle&sort=top&period=all')), page: 2 })).toBe('/gallery?sort=top&format=rap_battle&page=2');
    expect(galleryHref(galleryFilters(new URLSearchParams('sort=new&period=week&voices=premium')))).toBe('/gallery?sort=new&voices=premium');
    expect(galleryHref({ ...galleryFilters(new URLSearchParams('lang=ru&format=rap_battle')), page: 2 })).toBe('/gallery?format=rap_battle&lang=ru&page=2');
    expect(galleryHref(galleryFilters(new URLSearchParams('lang=all')))).toBe('/gallery?lang=all');
  });
});

describe('order', () => {
  it('joins the sort and the top sort\'s period into one choice and back', () => {
    expect(orderOf(galleryFilters(new URLSearchParams()))).toBe('trending');
    expect(orderOf(galleryFilters(new URLSearchParams('sort=new&period=week')))).toBe('new');
    expect(orderOf(galleryFilters(new URLSearchParams('sort=top&period=week')))).toBe('top:week');
    expect(orderParams('trending')).toEqual({ sort: null, period: null });
    expect(orderParams('new')).toEqual({ sort: 'new', period: null });
    expect(orderParams('top:month')).toEqual({ sort: 'top', period: 'month' });
    expect(orderParams('top:all')).toEqual({ sort: 'top', period: null });
  });
});
