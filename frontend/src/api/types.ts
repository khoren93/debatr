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
/** none: one card per debate; motion: one card per topic, its best version on the cover. */
export type GalleryGroup = 'none' | 'motion';
/** Show formats (backend services/formats). */
export type FormatId = 'debate' | 'rap_battle';
/** A debater's side; absent on configs from before sides (the persona carried the stance). */
export type DebaterSide = 'for' | 'against' | 'own';
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
  /** The format's name for this part of the show ("Round 2", "Verdict"). */
  round_label?: string;
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
  side?: DebaterSide | null;
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
  /** The judge's score per round (rap battles), participant id -> score; empty otherwise. */
  rounds?: { round: number; scores: Record<string, number> }[];
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
  /** Rap battles: speaker id -> flow (how the rapper sounds in the track), in place of a voice. */
  flows?: Record<string, string>;
  /** Crowd / studio reactions in the video; unset: the format's default. */
  sfx?: boolean | null;
}

// --- AI covers (backend services/media/cover.py) ------------------------------------------

export type CoverStatus = 'none' | 'queued' | 'running' | 'ready' | 'error';
/** Why the owner cannot ask for a cover now (the browser's own OpenRouter key still can when
 *  it is `no_balance`). */
export type CoverBlocker = 'off' | 'not_finished' | 'busy' | 'no_balance';

/** One AI cover version: 16:9 at 1536 and 768 px wide, YouTube's 1280×720 JPEG, the 1200×630
 *  link preview. */
export interface CoverImage {
  id: string;
  url: string;
  small_url: string;
  yt_url: string;
  og_url: string;
  hook: string;
  source: 'auto' | 'owner' | 'admin' | string;
  created_at: string | null;
}

/** A debate's cover: the one shown (null: the markup cover) and the latest build; versions,
 *  the error, the price and whether a new one can be asked for come only to the owner. */
export interface Cover {
  status: CoverStatus;
  current: CoverImage | null;
  versions: CoverImage[];
  error: string | null;
  can_generate: boolean;
  reason: CoverBlocker | null;
  price_usd: number;
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
  /** The AI cover shown (null: the markup cover) and the latest build's state. */
  cover: CoverImage | null;
  cover_status: CoverStatus;
}

export interface DebateSettings {
  format: string;
  topic: string;
  description: string | null;
  language: string;
  language_code: string;
  num_rounds: number;
  length_preset: string;
  intensity: number;
  output_style: OutputStyle;
  /** The news story behind a trending topic (public, so a remix keeps it). */
  news: NewsContext | null;
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
  author_official?: boolean; // by the site's own account: the logo as the avatar, the official mark
  is_owner: boolean;
  is_public: boolean;
  slug: string | null;
  /** The public page's canonical path (`/d/{slug}/{topic-words}`, backend services/seo); null
   *  while private. `share_url` is its absolute address. */
  path: string | null;
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
  /** The topic's public versions (null while it has none). */
  motion: MotionDetail | null;
  /** The public debate this one remixes. */
  remix_of: RemixParent | null;
  cover: Cover;
}

// --- Topics (backend services/motions) ----------------------------------------

/** A topic as the gallery sees it: counted over its public versions only. */
export interface MotionRef {
  slug: string;
  /** The first public version's topic. */
  title: string;
  versions: number;
  /** Debater models across the versions. */
  models: string[];
  /** The topic page's canonical path. */
  path: string;
}

/** One public version of a topic (no verdict: the audience votes blind). */
export interface MotionVersion {
  id: string;
  slug: string;
  topic: string;
  language: string;
  language_code: string;
  author_name: string | null;
  author_official?: boolean; // by the site's own account: the logo as the avatar, the official mark
  participants: Participant[];
  likes: number;
  views: number;
  duration_ms: number | null;
  premium_voices: boolean;
  published_at: string | null;
  /** The debate being viewed. */
  current: boolean;
  path: string;
}

export interface MotionDetail {
  slug: string;
  title: string;
  versions: number;
  items: MotionVersion[];
  path: string;
}

export interface RemixParent {
  slug: string;
  topic: string;
  path: string;
}

/** `/t/:slug`: a topic and every public version of it. */
export interface MotionPage {
  slug: string;
  title: string;
  versions: number;
  items: GalleryItem[];
  /** Canonical path (`/t/{slug}/{topic-words}`): other spellings redirect to it. */
  path: string;
}

/** The topic a wizard text would join, and similar topics to take the wording of. */
export interface MotionSuggestions {
  match: MotionRef | null;
  similar: MotionRef[];
}

export interface ParticipantConfig {
  role: ParticipantRole;
  model_id: string;
  display_name: string;
  avatar_url?: string;
  voice_name?: string;
  persona_preset?: string;
  persona_custom?: string;
  side?: DebaterSide;
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
  format?: FormatId;
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
  /** An AI cover once it completes: unset follows the rule (runs paid from the balance or an own
   *  key), false never. */
  cover?: boolean | null;
  draft?: boolean;
  user_provider_key?: string;
  /** Browser-only ElevenLabs key for the automatic audio build (never stored server-side). */
  user_tts_key?: string;
  /** Id of the debate this one remixes (request-only; links it and keeps a translation in its topic). */
  remix_of?: string;
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
  /** A rap battle's generated track: its length and price in credits (like tts_cost_usd). */
  music_ms: number;
  music_cost_usd: number;
  /** The run gets an AI cover when it completes, and what it adds to credits_cost_usd (0 on an
   *  own OpenRouter key). */
  cover: boolean;
  cover_cost_usd: number;
  own_key: boolean;
  own_tts_key: boolean;
  paid_models: string[];
  credits_before: number | null;
  credits_after: number | null;
  /** What the API token making the request may still spend (null in the browser). */
  token_budget_usd: number | null;
  sufficient: boolean;
  /** A debate on free models without credits or an own key: the day's allowance… */
  free_runs: FreeRuns | null;
  /** …and why it would be refused (too big, or none left today). */
  free_limit: string | null;
}

export interface PublishResponse {
  is_public: boolean;
  slug: string | null;
  share_url: string | null;
  path?: string | null;
  /** 'flagged' when the debate was queued for a review instead of going public. */
  moderation_status: ModerationStatus;
}

// --- Accounts & billing ------------------------------------------------------

export interface User {
  id: string;
  email: string;
  display_name: string;
  avatar_seed: string;
  official?: boolean; // the site's own account: the logo is its avatar
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
  free_debates: FreeDebates;
  /** AI covers (a lever): off | paid | all_public, and what one costs from the balance. */
  ai_covers: 'off' | 'paid' | 'all_public';
  cover_price_usd: number;
  /** The presence beacon (lib/presence.ts); false: the site sends none. */
  analytics?: boolean;
}

/** Limits of debates on free models for accounts without credits or an own OpenRouter key
 * (services/free_limits; 0 or an empty list: none). */
export interface FreeDebates {
  per_day: number;
  max_rounds: number;
  max_debaters: number;
  lengths: LengthPreset[];
}

export interface FreeRuns {
  per_day: number;
  used: number;
  left: number;
  /** When a run leaves the 24-hour window, once none is left. */
  next_at: string | null;
}

export type PaymentsMode = 'stripe' | 'dev' | 'disabled';

export interface BillingConfig {
  topup_amounts: number[];
  currency: string;
  payments_mode: PaymentsMode;
  signup_bonus_usd: number;
  tts_price_per_1k_chars: number;
  tts_price_per_min: number;
  /** A rap battle's generated music on the system key, per minute of track. */
  music_price_per_min: number;
  /** A typical paid debate at today's prices (two rounds, short replies, models priced like
   *  Claude Sonnet / GPT, its AI cover), with free voices and with premium ones. */
  debate_usd: number;
  voiced_debate_usd: number;
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
export type TransactionCategory = 'models' | 'voices' | 'pictures' | 'music' | 'cover' | 'topup' | 'bonus' | 'refund' | 'adjustment';

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
  format: string;
  title: string | null;
  topic: string;
  language: string;
  language_code: string;
  category: string | null;
  author_name: string | null;
  author_official?: boolean; // by the site's own account: the logo as the avatar, the official mark
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
  /** The topic this debate is a version of. */
  motion: MotionRef | null;
  /** Canonical path of the debate's page. */
  path: string;
  /** The AI cover (null: the markup cover). */
  cover: CoverImage | null;
}

export interface GalleryLanguage {
  /** Two-letter code, as `GalleryItem.language_code`. */
  code: string;
  /** Cards in this language under the request's other filters. */
  count: number;
}

export interface GalleryResponse {
  items: GalleryItem[];
  /** Debates, or topics with `group=motion`. */
  total: number;
  categories: string[];
  /** Every language with cards under the other filters, most cards first. */
  languages: GalleryLanguage[];
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
  round_label?: string;
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
  /** Rap battles: speaker id -> flow, in place of the rappers' voices. */
  flows?: Record<string, string>;
  /** Crowd / studio reactions in the video; unset: the format's default. */
  sfx?: boolean | null;
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
  /** Own ElevenLabs key: whether its plan is a paid one (the Music API of rap battles needs it). */
  paid_plan?: boolean | null;
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
  /** Whose list it is on (a rap battle has its own: rivalries). */
  format: FormatId;
  /** 1 = hottest within that list. */
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
  /** The list shown: the format asked for when it writes topics its own way, else "debate". */
  format: FormatId;
  /** When the batch was built; null before the first one. */
  updated_at: string | null;
  topics: TrendingTopic[];
  /** Every category in display order, with its topic count. */
  categories: { id: TrendingCategoryId | string; count: number }[];
}

/** `GET /topics/trending/search`: earlier batches' topics that match, newest first. */
export interface TrendingArchive {
  format: FormatId;
  topics: TrendingTopic[];
}

/** `POST /topics/ideas`: the wizard's AI button (backend services/topic_ideas.py). */
export interface TopicIdeas {
  format: FormatId;
  /** Best first; empty when the model would not write topics on the text. */
  ideas: string[];
}
