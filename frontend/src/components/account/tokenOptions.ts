/** Form state of a new API token (Account page and the /device approval), kept in a .ts file
 *  for react-refresh. */
import type { NewApiToken } from '../../api/types';
import type { SegmentOption } from '../ui';

export type ExpiryChoice = '30' | '90' | '365' | 'never';

export const EXPIRY_OPTIONS: SegmentOption<ExpiryChoice>[] = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
  { value: 'never', label: 'Never' },
];

export interface TokenOptions {
  name: string;
  expiry: ExpiryChoice;
  /** Dollars as typed; empty = no limit. */
  limit: string;
}

const MAX_LIMIT = 100_000;

/** The request body, or a message for the form. */
export const tokenRequest = (options: TokenOptions): { body: NewApiToken; error?: undefined } | { error: string } => {
  const name = options.name.trim().replace(/\s+/g, ' ');
  if (!name) return { error: 'Give the token a name' };
  if (name.length > 100) return { error: 'Use at most 100 characters for the name' };
  const raw = options.limit.trim().replace(/^\$\s*/, '').replace(',', '.');
  let limit: number | null = null;
  if (raw) {
    limit = Number(raw);
    if (!Number.isFinite(limit) || limit < 0 || limit > MAX_LIMIT) return { error: 'Enter the spending limit in dollars, e.g. 5' };
  }
  return { body: { name, expires_in_days: options.expiry === 'never' ? null : Number(options.expiry), spend_limit_usd: limit } };
};
