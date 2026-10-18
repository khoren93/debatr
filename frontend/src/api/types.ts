import type { Scene, SceneCheck } from './visuals';

export type DebateStatus = 'draft' | 'queued' | 'running' | 'completed' | 'error' | 'stopped';
export type ParticipantRole = 'moderator' | 'debater';
export type LengthPreset = 'very_short' | 'short' | 'medium' | 'long';
export type OutputStyle = 'markdown' | 'spoken';
export type MediaStatus = 'none' | 'queued' | 'running' | 'ready' | 'error';
export type TTSProviderName = 'elevenlabs' | 'edge';
export type MediaOutput = 'audio' | 'video' | 'short';
export type VideoQuality = '720p' | '1080p' | '4k';
/** Pictures among the visual scenes: none, free photos (Wikimedia Commons) or AI images (paid). */
export type ImageSource = 'off' | 'stock' | 'ai';

export const ACTIVE_STATUSES: readonly DebateStatus[] = ['queued', 'running'];
export const GALLERY_CATEGORIES = ['tech', 'society', 'science', 'culture', 'money', 'fun'] as const;
export type GalleryCategory = (typeof GALLERY_CATEGORIES)[number];
export type GallerySort = 'new' | 'trending' | 'top';
export type GalleryPeriod = 'week' | 'month' | 'year' | 'all';

// --- Models ------------------------------------------------------------------

export interface ModelInfo {
  id: string;
  name: string;
  context_length: number;
  pricing: { prompt: string; completion: string };
  is_free: boolean;
  description: string;
  /** Unix seconds the model was added to OpenRouter (0 = unknown). */
  created: number;
}

export interface ModelsResponse {
  data: ModelInfo[];
  timestamp: number;
}

export interface CreditsResponse {
  credits: number | null;
  error: string | null;
}

export interface ValidationResult {
  model_id: string;
  status: 'ok' | 'error';
  error: string | null;
}

// --- Debates -----------------------------------------------------------------

export interface TurnUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost: number;
}

export interface DebateTotals {
  tokens_in: number;
  tokens_out: number;
  cost: number;
  turns_count: number;
}

/** Live scenes of a turn (backend services/studio.py). */
export interface TurnScene {
  key: string;
  scene: Scene;
  /** Sent to the fact-checker (the result may still be pending). */
  checkable: boolean;
  check: SceneCheck | null;
}

export interface TurnVisuals {
  /** designing | checking (sketches / fact-checks running) | ready | error | none */
  status: 'designing' | 'checking' | 'ready' | 'error' | 'none';
  scenes: TurnScene[];
  /** Scenes of earlier turns this turn challenged. */
  disputes: { key: string; reason: string }[];
}

export interface Turn {
  seq_index: number;
  round_id: string;
  turn_type: string;
  speaker_role: ParticipantRole;
  speaker_id?: string; // "participant_{i}" | "judge"
  speaker_name: string;
  text: string;
  error: string | null;
  model_used: string;
  usage: TurnUsage;
  created_at: string | null;
  visuals?: TurnVisuals | null;
}

export interface Participant {
  id?: string; // "participant_{i}", matches Turn.speaker_id
  name: string | null;
  role: ParticipantRole | string;
  model: string;
  /** Set when a router picked `model` (Free Router: the model of the first answer is kept). */
  router?: string | null;
  voice_name: string | null;
  avatar: string | null;
}

export interface VerdictFeedback {
  speaker_id: string;
  name: string;
  text: string;
}

export interface Verdict {
  winner_id: string | null;
  winner_name: string | null;
  is_draw: boolean;
  headline: string;
  feedback: VerdictFeedback[];
}

export interface MediaPlan {
  provider: TTSProviderName;
  model_id: string;
  voices: Record<string, string>; // speaker id -> provider voice id
  outputs: MediaOutput[];
  quality: VideoQuality;
  /** Charts / drawn scenes, live next to the text and in the video (default on). */
  visuals?: boolean;
  /** Pictures among the scenes (default off). */
  images?: ImageSource;
}

export interface DebateSummary {
  id: string;
  title: string | null;
  topic: string;
  status: DebateStatus;
  media_status: MediaStatus;
  created_at: string;
  ended_at: string | null;
  totals: DebateTotals;
  is_public: boolean;
  slug: string | null;
  moderation_status: ModerationStatus;
  category: string | null;
  views: number;
  likes: number;
  votes: number;
  duration_ms: number | null;
  outputs: MediaOutput[];
  verdict: Verdict | null;
  participants: Participant[];
}

export interface DebateSettings {
  topic: string;
  description: string | null;
  language: string;
  language_code: string;
  num_rounds: number;
  length_preset: string;
  intensity: number;
  output_style: OutputStyle;
}

/** Why the viewer cannot vote / like (null when they can). */
export type EngagementBlocker = 'sign_in' | 'owner' | 'not_public' | 'not_finished';

export interface Audience {
  total: number;
  /** participant_id -> votes */
  counts: Record<string, number>;
  my_vote: string | null;
  can_vote: boolean;
  reason: EngagementBlocker | null;
}

export interface Engagement {
  likes: number;
  liked: boolean;
  can_like: boolean;
  audience: Audience;
}

/** Gallery check of a finished debate (backend services/moderation.py). */
export type ModerationStatus = 'none' | 'approved' | 'flagged' | 'rejected';

export interface Moderation {
  status: ModerationStatus;
  /** Why the AI check asked for a human review (owner only). */
  reason: string | null;
  /** The owner asked for the gallery while the debate waits for review. */
  publish_requested: boolean;
}

export interface DebateDetail {
  id: string;
  status: DebateStatus;
  media_status: MediaStatus;
  title: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  settings: DebateSettings;
  totals: DebateTotals;
  participants: Participant[];
  turns: Turn[];
  user_id: string | null;
  author_name: string | null;
  is_owner: boolean;
  is_public: boolean;
  slug: string | null;
  share_url: string | null;
  category: string | null;
  views: number;
  published_at: string | null;
  verdict: Verdict | null;
  media_plan: MediaPlan | null;
  duration_ms: number | null;
  outputs: MediaOutput[];
  billing: { own_key: boolean };
  engagement: Engagement;
  /** Full stored configuration; only present for the owner (drafts re-open in the wizard). */
  config: DebateConfig | null;
  /** Gallery check; only present for the owner and the admin. */
  moderation: Moderation | null;
}

export interface ParticipantConfig {
  role: ParticipantRole;
  model_id: string;
  display_name: string;
  avatar_url?: string;
  voice_name?: string;
  persona_preset?: string;
  persona_custom?: string;
}

/** The news story behind a trending topic; its brief goes into every prompt (backend NewsContext). */
export interface NewsContext {
  brief: string;
  outlet?: string;
  title?: string;
  /** Link to the original article (http/https). */
  url?: string;
  published_at?: string | null;
}

export interface DebateConfig {
  topic: string;
  description?: string;
  /** Ground the debate in the news story the topic came from (trending topics). */
  news?: NewsContext | null;
  language: string;
  participants: ParticipantConfig[];
  debate_preset_id?: string;
  length_preset: LengthPreset;
  num_rounds: number;
  intensity?: number;
  output_style?: OutputStyle;
  media_plan?: MediaPlan;
  /** Publish to the gallery once finished and approved by the AI check (default true). */
  auto_publish?: boolean;
  /** Web fact-check of the figures and quotes in the visual scenes (paid like the debate). */
  fact_check?: boolean;
  draft?: boolean;
  user_provider_key?: string;
  /** Browser-only ElevenLabs key for the automatic audio build (never stored server-side). */
  user_tts_key?: string;
}

export interface CreateDebateResponse {
  debate_id: string;
  status: string;
  message: string;
}

export interface Estimate {
  turns: number;
  words: number;
  tokens_in: number;
  tokens_out: number;
  llm_cost_usd: number;
  tts_chars: number;
  tts_cost_usd: number;
  factcheck_cost_usd: number;
  images_cost_usd: number;
  credits_cost_usd: number;
  duration_ms: number;
  render_ms: number;
  own_key: boolean;
  own_tts_key: boolean;
  paid_models: string[];
  credits_before: number | null;
  credits_after: number | null;
  /** What the API token making the request may still spend (null in the browser). */
  token_budget_usd: number | null;
  sufficient: boolean;
}

export interface PublishResponse {
  is_public: boolean;
  slug: string | null;
  share_url: string | null;
  /** 'flagged' when the debate was queued for a review instead of going public. */
  moderation_status: ModerationStatus;
}

// --- Accounts & billing ------------------------------------------------------

export interface User {
  id: string;
  email: string;
  display_name: string;
  avatar_seed: string;
  credits_usd: number;
  openrouter_key_masked: string | null;
  created_at: string;
}

/** Personal API token for the `debatr` CLI, scripts and AI agents (MCP). */
export interface ApiToken {
  id: string;
  name: string;
  /** "debatr_…a1b2" */
  token_hint: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  expired: boolean;
  /** null = no limit; 0 = free models only. */
  spend_limit_usd: number | null;
  spent_usd: number;
}

/** Returned once, when the token is created. */
export interface ApiTokenCreated extends ApiToken {
  token: string;
}

export interface NewApiToken {
  name: string;
  expires_in_days: number | null;
  spend_limit_usd: number | null;
}

export type DeviceStatus = 'pending' | 'approved' | 'denied' | 'expired';

/** A `debatr login` request waiting for approval in the browser. */
export interface DeviceRequest {
  user_code: string;
  client_name: string;
  status: DeviceStatus;
  expires_at: string;
}

/** `GET /api/status`: levers of the admin console the site reacts to. */
export interface SiteStatus {
  registration_open: boolean;
  /** New debates and audio builds are paused; running ones finish. */
  maintenance: boolean;
  maintenance_message: string | null;
}

export type PaymentsMode = 'stripe' | 'dev' | 'disabled';

export interface BillingConfig {
  topup_amounts: number[];
  currency: string;
  payments_mode: PaymentsMode;
  signup_bonus_usd: number;
  credit_markup: number;
  tts_price_per_1k_chars: number;
  tts_price_per_min: number;
  elevenlabs_available: boolean;
  /** Why premium voices are unavailable (key missing or rejected). */
  elevenlabs_error: string | null;
}

export interface CheckoutResponse {
  url: string;
  instant: boolean;
}

export interface ConfirmResponse {
  credited: boolean;
  amount_usd: number | null;
  credits_usd: number;
}

/** What a ledger row paid for (backend services/ledger.py). */
export type TransactionCategory = 'models' | 'voices' | 'pictures' | 'topup' | 'bonus' | 'refund' | 'adjustment';

export interface Transaction {
  id: string;
  amount_usd: number;
  balance_after_usd: number;
  kind: string;
  category: TransactionCategory | string;
  /** Debate title for charges, the description otherwise. */
  title: string;
  description: string | null;
  debate_id: string | null;
  provider: string | null;
  created_at: string;
}

/** One UTC day of this month's usage. */
export interface UsageDay {
  /** "2026-10-14" */
  date: string;
  tokens: number;
  voice_ms: number;
  renders: number;
  spent_usd: number;
}

export interface Usage {
  period_start: string;
  /** Every day from period_start through today. */
  days: UsageDay[];
  debates: number;
  tokens_in: number;
  tokens_out: number;
  voice_ms: number;
  renders: number;
  spent_usd: number;
  topped_up_usd: number;
  llm_usd: number;
  tts_usd: number;
}

// --- Gallery -----------------------------------------------------------------

export interface GalleryItem {
  id: string;
  slug: string;
  title: string | null;
  topic: string;
  language: string;
  category: string | null;
  author_name: string | null;
  views: number;
  likes: number;
  votes: number;
  duration_ms: number | null;
  has_media: boolean;
  /** The audio was voiced by ElevenLabs. */
  premium_voices: boolean;
  verdict: Verdict | null;
  participants: Participant[];
  published_at: string | null;
}

export interface GalleryResponse {
  items: GalleryItem[];
  total: number;
  categories: string[];
}

export interface LeaderboardEntry {
  model_id: string;
  name: string;
  is_free: boolean;
  rating: number;
  /** False until the model met another one in a debate that got audience votes (the rating is then just the 1000 baseline). */
  rated: boolean;
  /** Public debates the model argued in. */
  debates: number;
  /** Audience votes received. */
  votes: number;
  /** votes / all votes cast in its debates (null without votes). */
  vote_share: number | null;
  audience_wins: number;
  audience_contests: number;
  judge_wins: number;
  judge_contests: number;
  /** Web fact-checks of the model's on-screen figures and quotes. */
  claims_checked: number;
  claims_verified: number;
  claims_disputed: number;
}

export interface Leaderboard {
  entries: LeaderboardEntry[];
  total_debates: number;
  total_votes: number;
}

// --- Server-Sent Events -----------------------------------------------------

export interface TurnStartedEvent {
  seq_index: number;
  speaker_name: string;
  speaker_role: ParticipantRole;
  turn_type: string;
  round_id: string;
}

export interface TurnDeltaEvent {
  seq_index: number;
  delta: string;
  speaker_name?: string;
}

export interface DebateTerminalEvent {
  debate_id: string;
  status?: DebateStatus;
  message?: string;
  totals?: DebateTotals;
}

export interface VerdictReadyEvent {
  debate_id: string;
  verdict: Verdict;
}

export interface TurnVisualsEvent {
  seq_index: number;
  visuals: TurnVisuals;
}

// --- Media (audio + browser-side video) --------------------------------------

export interface MediaOptions {
  provider: TTSProviderName;
  model_id: string;
  voices: Record<string, string>; // speaker id -> provider voice id
  /** Design visual scenes for the video (default true). */
  visuals?: boolean;
  /** Pictures among the scenes (default off). */
  images?: ImageSource;
}

export interface GenerateMediaRequest extends MediaOptions {
  force?: boolean;
  user_tts_key?: string;
}

export interface MediaProgress {
  step: string;
  current: number;
  total: number;
  message: string;
  error: string | null;
}

export interface MediaUrls {
  timeline: string;
  full_mp3: string;
  full_wav: string;
  base: string;
}

export interface MediaStats {
  chars: number;
  tts_ms: number;
  estimated_usd: number | null;
  total_ms: number;
  cached_turns: number;
}

export interface DebateMedia {
  debate_id: string;
  media_status: MediaStatus;
  progress: MediaProgress;
  options: MediaOptions | null;
  urls: MediaUrls | null;
  stats: MediaStats | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface VoiceInfo {
  id: string;
  name: string;
  description: string | null;
  preview_url: string | null;
  gender: string | null;
  languages: string[];
}

export interface VoicesResponse {
  provider: TTSProviderName;
  /** ISO code of the debate language; `voices[].languages` use the same codes. */
  language: string;
  voices: VoiceInfo[];
  defaults: Record<string, string>;
}

export interface MediaCapabilities {
  elevenlabs: boolean;
  edge: boolean;
  ffmpeg: boolean;
  default_provider: TTSProviderName;
  default_model_id: string;
  elevenlabs_models: string[];
  /** Why premium voices are unavailable (key missing or rejected). */
  elevenlabs_error: string | null;
}

// --- Trending topics (GET /topics/trending, backend services/trending.py) ---
export type TrendingCategoryId = 'politics' | 'world' | 'business' | 'tech' | 'science' | 'health' | 'culture' | 'sports' | 'lifestyle';

export interface TrendingSource {
  title: string;
  /** Link to the original article (http/https only). */
  url: string;
  outlet: string;
  published_at: string | null;
}

export interface TrendingTopic {
  id: string;
  /** 1 = hottest. */
  rank: number;
  /** Short chip title. */
  label: string;
  /** The motion, ready for `topic`. */
  question: string;
  /** What happened (the models do not know recent news), ready for `description`. */
  brief: string;
  category: TrendingCategoryId | string;
  /** 1-10. */
  heat: number;
  /** Distinct outlets that carry the story. */
  outlets: number;
  sources: TrendingSource[];
}

export interface TrendingTopics {
  /** When the batch was built; null before the first one. */
  updated_at: string | null;
  topics: TrendingTopic[];
  /** Every category in display order, with its topic count. */
  categories: { id: TrendingCategoryId | string; count: number }[];
}
