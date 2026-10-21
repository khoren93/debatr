/** Words and numbers of the Audience pages (pure; a .ts file for react-refresh). */
import type { VisitVerdict } from '../../../api/admin/types';
import { SOURCE_LABELS } from '../charts/palette';
import { formatSpan } from '../helpers';

const regions = (() => {
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' });
  } catch {
    return null;
  }
})();

/** "Armenia" for "AM"; "Unknown" without a code. */
export const countryName = (code: string | null | undefined): string => {
  if (!code) return 'Unknown';
  try {
    return regions?.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
};

/** The flag emoji of a two-letter country code ("" without one). */
export const flagOf = (code: string | null | undefined): string => {
  if (!code || !/^[A-Za-z]{2}$/.test(code)) return '';
  return String.fromCodePoint(...[...code.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
};

/** "Yerevan, Armenia" (a city named like its region once). */
export const placeText = (place: { country: string | null; region: string | null; city: string | null }): string => {
  const parts = [place.city, place.region !== place.city ? place.region : null, place.country ? countryName(place.country) : null].filter(Boolean);
  return parts.length ? parts.join(', ') : 'Unknown place';
};

/** "45 s", "12 min" for milliseconds; "—" for none. */
export const duration = (ms: number | null | undefined): string => (ms === null || ms === undefined ? '—' : ms < 1000 ? '0 s' : formatSpan(ms / 1000));

export const sourceLabel = (source: string): string => (SOURCE_LABELS as Record<string, string>)[source] ?? source;

export const DEVICE_LABELS: Record<string, string> = { desktop: 'Desktop', mobile: 'Phone', tablet: 'Tablet' };

export const SECTION_LABELS: Record<string, string> = {
  home: 'Home',
  debate: 'Debate pages',
  topic: 'Topic pages',
  gallery: 'Gallery',
  ranking: 'Model ranking',
  create: 'Create (wizard)',
  library: 'Library',
  'own debate': 'Own debate (live)',
  account: 'Account',
  'sign-in': 'Sign in / up',
  'CLI login': 'CLI login',
  privacy: 'Privacy',
  other: 'Other',
};

/** "en" → "English" (browser language codes of visitors). */
const languages = (() => {
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' });
  } catch {
    return null;
  }
})();
export const languageName = (code: string): string => {
  if (!code) return 'Unknown';
  try {
    return languages?.of(code) ?? code;
  } catch {
    return code;
  }
};

/** The site's actions in the console's words (backend services/audience/collect.ACTIONS). */
export const ACTION_LABELS: Record<string, string> = {
  signup: 'Created an account',
  login: 'Signed in',
  logout: 'Signed out',
  video_play: 'Played a video',
  video_progress: 'Watched part of a video',
  like: 'Liked a debate',
  vote: 'Voted who won',
  share: 'Opened Share',
  copy_link: 'Copied a link',
  copy_embed: 'Copied the embed code',
  remix: 'Started a remix',
  verdict_reveal: 'Revealed the verdict',
  export_mp4: 'Exported an MP4',
  download_mp3: 'Downloaded the MP3',
  wizard_step: 'Moved on in the wizard',
  topic_pick: 'Picked a trending topic',
  topic_ideas: 'Asked AI for topics',
  debate_start: 'Started a debate',
  draft_save: 'Saved a draft',
  checkout: 'Opened a top-up',
  topup: 'Topped up credits',
  cli_login: 'Approved a CLI login',
  token_create: 'Created an API token',
  gallery_filter: 'Filtered the gallery',
};

/** A visit's verdict in the console's words (backend services/audience/bots.py). */
export const VERDICT_LABELS: Record<VisitVerdict, string> = {
  human: 'Person',
  likely_human: 'Likely a person',
  unclear: 'Unclear',
  suspect: 'Suspicious',
  bot: 'Bot',
  agent: 'AI agent',
};

export const VERDICT_HINTS: Record<VisitVerdict, string> = {
  human: 'Input only a hand makes, nothing machine-like',
  likely_human: 'Some human input, no sign of automation',
  unclear: 'Too little to tell yet (a visit that has just begun, or one from before input was counted)',
  suspect: 'Signs of automation next to human ones: a VPN, a cloud browser, or an agent in someone’s browser',
  bot: 'An automated browser that does not interact: a crawler or a script',
  agent: 'Automation that clicks and types: an AI agent or a scripted browser',
};

export const VERDICT_COLORS: Record<VisitVerdict, string> = {
  human: 'var(--color-ok)',
  likely_human: 'var(--color-mint)',
  unclear: 'var(--color-muted)',
  suspect: 'var(--color-host)',
  bot: 'var(--color-danger)',
  agent: 'var(--color-violet)',
};

export const VERDICT_ORDER: VisitVerdict[] = ['human', 'likely_human', 'unclear', 'suspect', 'agent', 'bot'];

export const isVerdict = (value: string): value is VisitVerdict => value in VERDICT_LABELS;
