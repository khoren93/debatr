/** URL-held filters of the console's lists (pure; a .ts file for react-refresh). */

export interface FilterSpec {
  /** The URL parameter. */
  key: string;
  label: string;
  /** Choices; the first, with value '', is "any". */
  options: { value: string; label: string }[];
}

/** The parameter's value when it is one of the choices, '' otherwise. */
export const pick = (params: URLSearchParams, spec: FilterSpec): string => {
  const value = params.get(spec.key) ?? '';
  return spec.options.some((o) => o.value === value) ? value : '';
};

export const pickKey = (params: URLSearchParams, specs: FilterSpec[], key: string): string => {
  const spec = specs.find((f) => f.key === key);
  return spec ? pick(params, spec) : '';
};

export const flag = (value: string) => (value === 'true' ? true : value === 'false' ? false : undefined);

/** "YYYY-MM-DD" of the UTC day `days - 1` days before today (today counts as one). */
export const utcDaysBack = (days: number) => new Date(Date.now() - (days - 1) * 86_400_000).toISOString().slice(0, 10);

export const pageOf = (params: URLSearchParams) => Math.max(0, Number.parseInt(params.get('page') ?? '0', 10) || 0);

/** A copy of the parameters with `changes` applied ('' removes one); any change but paging
 * starts again at page one. */
export const withChanges = (params: URLSearchParams, changes: Record<string, string>) => {
  const next = new URLSearchParams(params);
  for (const [name, value] of Object.entries(changes)) {
    if (value) next.set(name, value);
    else next.delete(name);
  }
  if (!('page' in changes)) next.delete('page');
  return next;
};

/** Sort keys whose first click sorts A–Z; the rest (numbers, dates) start high. */
export const nextOrder = (current: { sort?: string; order?: 'asc' | 'desc' }, sort: string, ascFirst: string[] = []) => {
  if (current.sort === sort) return current.order === 'desc' ? 'asc' : 'desc';
  return ascFirst.includes(sort) ? 'asc' : 'desc';
};
