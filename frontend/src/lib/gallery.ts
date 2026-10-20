import { GALLERY_CATEGORIES, type FormatId, type GalleryCategory, type GalleryPeriod, type GallerySort } from '../api/types';
import { toQuery } from '../api/route';

/** The gallery's filters as they live in the URL (`?sort=top&period=week&format=rap_battle&…`):
 *  read by its route loaders and shown by the page. */

export type CategoryFilter = 'all' | GalleryCategory;
export type FormatFilter = 'all' | FormatId;

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

const oneOf = <T extends string>(value: string | null, options: { value: T }[], fallback: T): T => options.find((o) => o.value === value)?.value ?? fallback;

export interface GalleryFilters {
  sort: GallerySort;
  period: GalleryPeriod;
  format: FormatFilter;
  category: CategoryFilter;
  /** Only debates this model argued in. */
  model: string | null;
  /** Only debates voiced with premium (ElevenLabs) voices. */
  premium: boolean;
}

export const galleryFilters = (params: URLSearchParams): GalleryFilters => ({
  sort: oneOf(params.get('sort'), SORT_OPTIONS, 'trending'),
  period: oneOf(params.get('period'), PERIOD_OPTIONS, 'all'),
  format: oneOf(params.get('format'), FORMAT_OPTIONS, 'all'),
  category: oneOf(params.get('category'), CATEGORY_OPTIONS, 'all'),
  model: params.get('model')?.trim() || null,
  premium: params.get('voices') === 'premium',
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
    group: 'motion',
  })}`;
