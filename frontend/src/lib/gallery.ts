import { GALLERY_CATEGORIES, type FormatId, type GalleryCategory, type GalleryPeriod, type GallerySort } from '../api/types';
import { toQuery } from '../api/route';

/** The gallery's filters as they live in the URL (`?sort=top&period=week&format=rap_battle&…`,
 *  `&page=2`): read by its route loaders and shown by the page. */

/** The gallery shows English debates unless `?lang=` names another language (or `all`). */
export const DEFAULT_LANGUAGE = 'en';

/** Cards per gallery page. */
export const GALLERY_PAGE_SIZE = 24;
/** Pages past this are not served (the API's offset grows with them). */
export const GALLERY_MAX_PAGE = 500;

export type CategoryFilter = 'all' | GalleryCategory;
export type FormatFilter = 'all' | FormatId;
/** A two-letter language code (as `GalleryItem.language_code`) or every language. */
export type LanguageFilter = 'all' | (string & {});

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export const CATEGORY_OPTIONS: { value: CategoryFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  ...GALLERY_CATEGORIES.map((c) => ({ value: c, label: capitalize(c) })),
];

export const SORT_OPTIONS: { value: GallerySort; label: string }[] = [
  { value: 'trending', label: 'Trending' },
  { value: 'new', label: 'New' },
  { value: 'top', label: 'Top' },
];

export const PERIOD_OPTIONS: { value: GalleryPeriod; label: string }[] = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'year', label: 'Year' },
  { value: 'all', label: 'All time' },
];

export const FORMAT_OPTIONS: { value: FormatFilter; label: string }[] = [
  { value: 'all', label: 'All shows' },
  { value: 'debate', label: 'Debates' },
  { value: 'rap_battle', label: 'Rap battles' },
];

/** Sort and period as one choice ("Top this week"): `top:<period>` for the top sort. */
export type GalleryOrder = Exclude<GallerySort, 'top'> | `top:${GalleryPeriod}`;

export const orderOf = (f: Pick<GalleryFilters, 'sort' | 'period'>): GalleryOrder => (f.sort === 'top' ? `top:${f.period}` : f.sort);

/** The URL parameters of an order (defaults dropped). */
export const orderParams = (order: GalleryOrder): { sort: string | null; period: string | null } => {
  if (!order.startsWith('top:')) return { sort: order === 'trending' ? null : order, period: null };
  const period = order.slice(4);
  return { sort: 'top', period: period === 'all' ? null : period };
};

const oneOf = <T extends string>(value: string | null, options: { value: T }[], fallback: T): T => options.find((o) => o.value === value)?.value ?? fallback;

export interface GalleryFilters {
  sort: GallerySort;
  period: GalleryPeriod;
  format: FormatFilter;
  language: LanguageFilter;
  category: CategoryFilter;
  /** Only debates this model argued in. */
  model: string | null;
  /** Only debates voiced with premium (ElevenLabs) voices. */
  premium: boolean;
  /** 1-based page of GALLERY_PAGE_SIZE cards. */
  page: number;
}

const languageOf = (raw: string | null): LanguageFilter => {
  const value = raw?.trim().toLowerCase();
  return value === 'all' || (value && /^[a-z]{2}$/.test(value)) ? value : DEFAULT_LANGUAGE;
};

const pageOf = (raw: string | null) => {
  const page = Number(raw);
  return Number.isInteger(page) && page > 1 ? Math.min(page, GALLERY_MAX_PAGE) : 1;
};

export const galleryFilters = (params: URLSearchParams): GalleryFilters => ({
  sort: oneOf(params.get('sort'), SORT_OPTIONS, 'trending'),
  period: oneOf(params.get('period'), PERIOD_OPTIONS, 'all'),
  format: oneOf(params.get('format'), FORMAT_OPTIONS, 'all'),
  language: languageOf(params.get('lang')),
  category: oneOf(params.get('category'), CATEGORY_OPTIONS, 'all'),
  model: params.get('model')?.trim() || null,
  premium: params.get('voices') === 'premium',
  page: pageOf(params.get('page')),
});

/** `GET /api/gallery` for these filters: one card per topic. */
export const galleryPath = (f: GalleryFilters) =>
  `/gallery${toQuery({
    category: f.category === 'all' ? undefined : f.category,
    sort: f.sort,
    period: f.sort === 'top' ? f.period : undefined,
    model: f.model,
    premium_voices: f.premium || undefined,
    format: f.format === 'all' ? undefined : f.format,
    language: f.language === 'all' ? undefined : f.language,
    group: 'motion',
    limit: GALLERY_PAGE_SIZE,
    offset: f.page > 1 ? (f.page - 1) * GALLERY_PAGE_SIZE : undefined,
  })}`;

/** The gallery's address for these filters (defaults left out), e.g. for its page links. */
export const galleryHref = (f: GalleryFilters) =>
  `/gallery${toQuery({
    sort: f.sort === 'trending' ? undefined : f.sort,
    period: f.sort === 'top' && f.period !== 'all' ? f.period : undefined,
    format: f.format === 'all' ? undefined : f.format,
    lang: f.language === DEFAULT_LANGUAGE ? undefined : f.language,
    category: f.category === 'all' ? undefined : f.category,
    model: f.model,
    voices: f.premium ? 'premium' : undefined,
    page: f.page > 1 ? f.page : undefined,
  })}`;
