import type { DebateStatus, DebateSummary, MediaStatus, Participant, Turn } from '../api/types';

/** Completion price per 1M tokens, e.g. "$0.60". */
export const formatPrice = (pricing: { completion: string }) =>
  `$${(parseFloat(pricing.completion) * 1_000_000).toFixed(2)}`;

export const formatContext = (length: number) => {
  if (!length) return '?';
  if (length >= 1_000_000) return `${Math.round(length / 1_000_000)}M`;
  if (length >= 1000) return `${Math.round(length / 1000)}k`;
  return `${length}`;
};

export const formatCost = (cost: number) => {
  if (!cost) return '$0.00';
  return cost < 0.01 ? `$${cost.toFixed(4)}` : `$${cost.toFixed(2)}`;
};

/** Balance with two decimals: "$4.20", "−$0.12" (a balance that rounds to zero has no sign). */
export const formatMoney = (n: number) => {
  const cents = Math.round(n * 100);
  return `${cents < 0 ? '−' : ''}$${(Math.abs(cents) / 100).toFixed(2)}`;
};

/** Money with two decimals and a sign for ledgers: "+$5.00" / "−$0.12". */
export const formatSigned = (amount: number) => {
  const abs = Math.abs(amount);
  const text = abs < 0.01 && abs > 0 ? `$${abs.toFixed(4)}` : `$${abs.toFixed(2)}`;
  return amount < 0 ? `−${text}` : `+${text}`;
};

export const formatTokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);

export const formatCount = (n: number) => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return `${n}`;
};

export const formatDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString() : '';

/** "Sep 3, 2026" */
export const formatDateShort = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';

/** "4:13" (or "1:02:13" past an hour). */
export const formatDuration = (ms: number | null | undefined) => {
  if (!ms || ms <= 0) return '—';
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;
};

/** "https://www.bbc.co.uk/news/…" -> "bbc.co.uk" (empty for a missing or broken link). */
export const sourceDomain = (url: string | null | undefined) => {
  try {
    return url ? new URL(url).hostname.replace(/^www\./, '') : '';
  } catch {
    return '';
  }
};

/** Compact age for news: "45m", "3h", "2d" (empty without a date). */
export const formatAge = (iso: string | null | undefined, now: number = Date.now()) => {
  if (!iso) return '';
  const minutes = Math.max(1, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (!Number.isFinite(minutes)) return '';
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / 1440)}d`;
};

/** "~4 min" */
export const formatMinutes = (ms: number) => {
  const min = ms / 60_000;
  if (min < 1) return `${Math.max(1, Math.round(ms / 1000))}s`;
  return `${min < 10 ? min.toFixed(min < 2 ? 1 : 0) : Math.round(min)} min`;
};

export const STATUS_LABELS: Record<DebateStatus, string> = {
  draft: 'Draft',
  queued: 'Queued',
  running: 'Live',
  completed: 'Completed',
  error: 'Error',
  stopped: 'Stopped',
};

/** Colour token for a status pill (hex so it works in inline styles). */
export const STATUS_COLORS: Record<DebateStatus, string> = {
  draft: '#8B90A0',
  queued: '#FFC46B',
  running: '#FFC46B',
  completed: '#52D889',
  error: '#FF7A66',
  stopped: '#8B90A0',
};

/** Where a debate is in its life cycle, for library cards and filters. */
export type Stage = 'draft' | 'live' | 'rendering' | 'completed' | 'error' | 'stopped';

export const stageOf = (status: DebateStatus, media: MediaStatus): Stage => {
  if (status === 'draft') return 'draft';
  if (status === 'queued' || status === 'running') return 'live';
  if (status === 'completed' && (media === 'queued' || media === 'running')) return 'rendering';
  if (status === 'completed') return 'completed';
  if (status === 'error') return 'error';
  return 'stopped';
};

export const STAGE_LABELS: Record<Stage, string> = {
  draft: 'Draft',
  live: 'Live',
  rendering: 'Rendering',
  completed: 'Completed',
  error: 'Error',
  stopped: 'Stopped',
};

export const STAGE_COLORS: Record<Stage, string> = {
  draft: '#8B90A0',
  live: '#FF4D4D',
  rendering: '#FFC46B',
  completed: '#52D889',
  error: '#FF7A66',
  stopped: '#8B90A0',
};

export const stageOfSummary = (d: Pick<DebateSummary, 'status' | 'media_status'>) => stageOf(d.status, d.media_status);

/** Turns saved before v0.2 stored errors inline as "[Error ...]" text. */
export const isErrorTurn = (turn: Pick<Turn, 'error' | 'text'>) =>
  Boolean(turn.error) || turn.text.trim().startsWith('[Error');

export const turnErrorMessage = (turn: Pick<Turn, 'error' | 'text'>) => {
  if (turn.error) return turn.error;
  const legacy = turn.text.trim();
  const match = legacy.match(/OpenRouter Error \d+: (.*)/);
  if (match) {
    try {
      const parsed = JSON.parse(match[1].replace(/\]$/, ''));
      if (parsed?.error?.message) return `API Error: ${parsed.error.message}`;
    } catch {
      /* fall through */
    }
  }
  return legacy.replace(/^\[Error(?: generating response)?:?\s*/, '').replace(/\]$/, '');
};

export const roundLabel = (roundId: string) => {
  if (roundId === 'verdict') return 'Verdict';
  const match = roundId.match(/^round_(\d+)$/);
  return match ? `Round ${match[1]}` : roundId;
};

export const TURN_TYPE_LABELS: Record<string, string> = {
  moderator_intro: 'Intro',
  moderator_transition: 'Transition',
  moderator_comment: 'Moderator',
  opening: 'Opening',
  rebuttal: 'Rebuttal',
  closing: 'Closing',
  argument: 'Argument',
  verdict: 'Verdict',
};

/** "ROUND 1 · OPENING" */
export const roundHeading = (roundId: string, turnType: string) => {
  const round = roundLabel(roundId).toUpperCase();
  const type = TURN_TYPE_LABELS[turnType];
  return roundId === 'verdict' || !type || turnType.startsWith('moderator') ? round : `${round} · ${type.toUpperCase()}`;
};

/** Leading "[emotion]" cue of a spoken turn, if any. */
export const splitEmotionTag = (text: string): { tone: string | null; body: string } => {
  const match = text.match(/^\s*\[([a-z][a-z ]{1,24})\]\s*/i);
  if (!match) return { tone: null, body: text };
  return { tone: match[1].toLowerCase(), body: text.slice(match[0].length) };
};

// --- Speaker colours --------------------------------------------------------

export const HOST_COLOR = '#FFC46B';
export const JUDGE_COLOR = '#D9FF3D';
export const DEBATER_COLORS = ['#6C9CFF', '#FF7A66', '#A78BFA', '#34D399', '#F472B6', '#60A5FA', '#FB7185', '#FBBF24'];

export const debaterColor = (index: number) => DEBATER_COLORS[index % DEBATER_COLORS.length];

/** Colour for a speaker id ("participant_i" | "judge") given the participant list. */
export const speakerColor = (speakerId: string | undefined, participants: Participant[]) => {
  if (speakerId === 'judge') return JUDGE_COLOR;
  const idx = participants.findIndex((p, i) => (p.id ?? `participant_${i}`) === speakerId);
  if (idx < 0) return '#8B90A0';
  const p = participants[idx];
  if (p.role === 'moderator') return HOST_COLOR;
  const debaterIndex = participants.slice(0, idx).filter((x) => x.role !== 'moderator').length;
  return debaterColor(debaterIndex);
};

/** Colour by speaker name (turns created before speaker ids existed). */
export const speakerColorByName = (name: string, participants: Participant[]) => {
  if (name.includes('Verdict')) return JUDGE_COLOR;
  const idx = participants.findIndex((p) => p.name === name);
  if (idx < 0) return '#8B90A0';
  return speakerColor(participants[idx].id ?? `participant_${idx}`, participants);
};

/** Short role tag: HOST / PRO / CON / 3RD… */
export const roleTag = (participant: Participant, participants: Participant[]) => {
  if (participant.role === 'moderator') return 'HOST';
  const debaters = participants.filter((p) => p.role !== 'moderator');
  const i = debaters.indexOf(participant);
  if (debaters.length <= 2) return i === 0 ? 'PRO' : 'CON';
  return i === 0 ? 'PRO' : i === 1 ? 'CON' : `SIDE ${i + 1}`;
};

export const initialOf = (name: string | null | undefined) => (name?.trim()?.[0] ?? '?').toUpperCase();

/** Deterministic gradient for card thumbnails. */
export const GRADIENTS = [
  'linear-gradient(140deg,#16224a,#3d1a16)',
  'linear-gradient(140deg,#1d3a2a,#3a2a10)',
  'linear-gradient(140deg,#2a1a4a,#0f2a3a)',
  'linear-gradient(140deg,#3a1a2a,#1a2a3a)',
  'linear-gradient(140deg,#1a3a3a,#3a3010)',
  'linear-gradient(140deg,#2a2a1a,#1a1a3a)',
];

export const gradientFor = (key: string) => {
  let hash = 0;
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return GRADIENTS[hash % GRADIENTS.length];
};

/** Model id -> "Claude Sonnet 4" style short name. */
export const shortModelName = (modelId: string) => {
  const raw = (modelId || '').split('/').pop() ?? modelId;
  return raw.replace(/:free$/, '').replace(/-/g, ' ');
};

export const providerOf = (modelId: string) => (modelId.includes('/') ? modelId.split('/')[0] : '');

/** Hide the studio markers ([visual: …], [dispute N: …]) while a turn streams; the worker strips
 *  them before the turn is saved. A marker still being typed at the end is hidden too. */
export const hideStudioMarkers = (text: string) =>
  text
    .replace(/[ \t]*\[\s*(?:visual|dispute)\b[^\]\n]*\]/gi, '')
    .replace(/[ \t]*\[\s*(?:v(?:i(?:s(?:u(?:a(?:l)?)?)?)?)?|d(?:i(?:s(?:p(?:u(?:t(?:e)?)?)?)?)?)?)(?:\b[^\]\n]*)?$/i, '');
