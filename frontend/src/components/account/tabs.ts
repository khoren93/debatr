/** Account page tabs; the active one lives in `?tab=` so other pages can link to it. */
export type AccountTab = 'overview' | 'keys' | 'billing' | 'security';

export const ACCOUNT_TABS: { value: AccountTab; label: string }[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'keys', label: 'API keys' },
  { value: 'billing', label: 'Billing' },
  { value: 'security', label: 'Security' },
];

export const parseAccountTab = (raw: string | null): AccountTab =>
  ACCOUNT_TABS.find((t) => t.value === raw)?.value ?? 'overview';

/** "/account" or "/account?tab=keys". */
export const accountPath = (tab: AccountTab = 'overview') => (tab === 'overview' ? '/account' : `/account?tab=${tab}`);
