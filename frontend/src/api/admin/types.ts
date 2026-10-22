// Mirrors backend/app/schemas/admin.py (the admin console API).

import type { ModelInfo } from '../types';

export type AdminRole = 'admin' | 'moderator';

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  role: AdminRole;
}

export interface AdminSessionInfo {
  id: string;
  created_at: string;
  /** Idle or absolute deadline, whichever comes first. */
  expires_at: string;
  /** The absolute deadline: activity does not extend it. */
  ends_at: string;
  sudo_until: string | null;
}

export interface AdminMe {
  user: AdminUser;
  csrf: string;
  session: AdminSessionInfo;
  recovery_codes_left: number;
  permissions: string[];
  /** The commit the server runs ("dev" locally without a build-arg). */
  version: string;
  /** False when ADMIN_SKIP_2FA (development) lets the console in with the password alone. */
  two_factor: boolean;
  /** Registered passkeys (sudo can take one instead of a code). */
  passkeys: number;
}

export interface AdminLoginOut {
  /** "done" with ADMIN_SKIP_2FA: already signed in, `me` is set. */
  next: 'totp' | 'enroll' | 'done';
  me?: AdminMe | null;
  /** With "totp": a passkey may answer instead of the code. */
  passkey: boolean;
}

export interface AdminPasskey {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  /** Synced passkey (iCloud Keychain, Google Password Manager…). */
  backed_up: boolean;
  transports: string[];
}

/** WebAuthn options as JSON (base64url fields), for navigator.credentials. */
export interface PasskeyOptions {
  options: Record<string, unknown>;
}

export interface EnrollStartOut {
  secret: string;
  otpauth_uri: string;
  /** SVG data URI of the QR code. */
  qr: string;
}

export interface AdminSignedIn {
  me: AdminMe;
  /** Only right after enrolling; shown once. */
  recovery_codes: string[] | null;
}

export interface AdminSessionRow {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  ip: string;
  user_agent: string;
  current: boolean;
}

// --- overview (backend/app/schemas/admin.py OverviewOut) ----------------------------------------

export type OverviewPeriod = '24h' | '7d' | '30d' | '90d' | 'all';

export interface Tile {
  value: number;
  /** The period before (null for "all"). */
  previous: number | null;
}

export interface OverviewUsers {
  new: Tile;
  active: Tile;
  total: number;
  dau: number;
  wau: number;
  mau: number;
}

export interface OverviewDebates {
  started: Tile;
  completed: Tile;
  failed: Tile;
  stopped: Tile;
  error_rate: Tile;
  running_now: number;
  media_ready: Tile;
  media_failed: Tile;
  renders: number;
  published: Tile;
  likes: Tile;
  votes: Tile;
  /** Whole UTC days (backend view_days); the 24 h period counts today. */
  views: Tile;
  /** The same days' views by source. */
  views_by_source: Partial<Record<string, number>>;
}

export interface OverviewMoney {
  topups: number;
  bonuses: number;
  refunds: number;
  adjustments: number;
  charged: Record<'models' | 'voices' | 'pictures' | 'music' | 'cover', number>;
  charged_total: number;
  cost_system: number;
  cost_user_keys: number;
  cost_by_purpose: Record<string, number>;
  margin: number;
  topups_previous: number | null;
  charged_total_previous: number | null;
  cost_system_previous: number | null;
  margin_previous: number | null;
  liabilities: number;
  negative_balances: number;
  negative_total: number;
  cost_tracked_since: string | null;
}

export interface SeriesPoint {
  t: string;
  signups: number;
  active: number | null;
  completed: number;
  error: number;
  stopped: number;
  charged: number | null;
  topups: number | null;
  cost: number | null;
  /** Views by source per whole UTC day (null in hourly series). */
  views_search: number | null;
  views_ai: number | null;
  views_social: number | null;
  views_embed: number | null;
  views_other: number | null;
  views_direct: number | null;
  views_internal: number | null;
}

/** Where a view came from (backend services/views.SOURCES), in the order charts stack them. */
export const VIEW_SOURCES = ['search', 'ai', 'social', 'embed', 'other', 'direct', 'internal'] as const;
export type ViewSource = (typeof VIEW_SOURCES)[number];

/** A site whose embedded players were watched (last 90 days). */
export interface EmbedSite {
  host: string;
  views: number;
}

export interface AttentionItem {
  key: string;
  severity: 'critical' | 'warning' | 'info';
  title: string;
  detail: string;
  href: string | null;
}

export interface TopModel {
  model: string;
  debates: number;
  turns: number;
  failure_rate: number | null;
  avg_ttft_ms: number | null;
  cost: number;
}

export interface TopSpender {
  user_id: string;
  email: string;
  display_name: string;
  spent: number;
}

export interface TopDebate {
  id: string;
  title: string;
  slug: string | null;
  /** The public page on the site, when published. */
  url: string | null;
  likes: number;
  views: number;
  votes: number;
}

export interface Overview {
  period: OverviewPeriod;
  start: string;
  end: string;
  previous_start: string | null;
  bucket: 'hour' | 'day' | 'week';
  generated_at: string;
  users: OverviewUsers;
  debates: OverviewDebates;
  money: OverviewMoney | null;
  series: SeriesPoint[];
  attention: AttentionItem[];
  top_models: TopModel[];
  top_spenders: TopSpender[] | null;
  top_debates: TopDebate[];
  /** The first day with views by source (they are kept since then). */
  views_since: string | null;
  embeds: EmbedSite[];
}

// --- users (backend/app/schemas/admin.py, routes_users.py) ------------------------------------

export type UserSort = 'created' | 'last_seen' | 'balance' | 'topped_up' | 'spent' | 'debates' | 'likes' | 'email';

/** Query parameters of the list and the CSV (unset = no filter). */
export interface UserFilters {
  q?: string;
  paid?: boolean;
  balance?: 'positive' | 'negative';
  own_key?: boolean;
  tokens?: boolean;
  status?: 'active' | 'disabled';
  staff?: boolean;
  /** UTC days, both inclusive (YYYY-MM-DD). */
  created_from?: string;
  created_to?: string;
  active_days?: number;
}

export interface SpendByCategory {
  models: number;
  voices: number;
  pictures: number;
  music: number;
  cover: number;
}

export interface AdminUserRow {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
  last_login_at: string | null;
  last_seen_at: string | null;
  is_active: boolean;
  role: AdminRole | null;
  credits_usd: number;
  own_key: boolean;
  tokens: number;
  topped_up: number;
  spent: number;
  spent_by: SpendByCategory;
  /** Runs, drafts left out. */
  debates: number;
  failed: number;
  public: number;
  /** Received on their debates. */
  likes: number;
  votes: number;
}

export interface AdminUserList {
  total: number;
  limit: number;
  offset: number;
  rows: AdminUserRow[];
}

export interface AdminUserProfile {
  id: string;
  email: string;
  display_name: string;
  avatar_seed: string;
  official?: boolean; // the site's own account
  email_verified?: boolean;
  /** Publishing and top-ups wait for the email to be confirmed. */
  email_required?: boolean;
  created_at: string;
  last_login_at: string | null;
  last_seen_at: string | null;
  is_active: boolean;
  role: AdminRole | null;
  two_factor: boolean;
  credits_usd: number;
  openrouter_key_masked: string | null;
}

export interface UserPeriodStats {
  debates: number;
  completed: number;
  failed: number;
  stopped: number;
  error_rate: number | null;
  free_debates: number;
  paid_debates: number;
  own_key_debates: number;
  token_debates: number;
  tokens_in: number;
  tokens_out: number;
  topped_up: number;
  /** Bonuses, refunds and positive adjustments. */
  credited: number;
  spent: number;
  spent_by: SpendByCategory;
  /** Model tokens charged per finished debate. */
  avg_debate_cost: number | null;
  /** What their runs cost us on the system keys. */
  cost_system: number;
}

export interface SpendDay extends SpendByCategory {
  day: string;
}

export interface UserApiToken {
  id: string;
  name: string;
  token_hint: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  expired: boolean;
  spend_limit_usd: number | null;
  spent_usd: number;
}

export interface ReactionOwner {
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  likes: number;
  votes: number;
}

export interface AuditEntry {
  id: string;
  created_at: string;
  actor_user_id?: string | null;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  reason: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip: string | null;
  user_agent?: string | null;
  ok: boolean;
}

export interface AdminUserCard {
  profile: AdminUserProfile;
  all_time: UserPeriodStats;
  last_30_days: UserPeriodStats;
  favorite_models: { model: string; debates: number }[];
  /** The last 30 UTC days. */
  spend_days: SpendDay[];
  tokens: UserApiToken[];
  reactions: { likes_given: number; votes_given: number; owners: ReactionOwner[] };
  audit: AuditEntry[];
  active_debates: number;
  public_debates: number;
  /** Admin accounts are disabled, deleted or given passwords only on the server. */
  protected: boolean;
}

export interface AdminLedgerRow {
  id: string;
  created_at: string;
  kind: string;
  category: string;
  title: string;
  description: string | null;
  amount_usd: number;
  balance_after_usd: number;
  debate_id: string | null;
  provider: string | null;
  provider_ref: string | null;
  /** Internal, for manual changes. */
  reason: string | null;
}

export interface AdminUserDebate {
  id: string;
  title: string;
  status: string;
  created_at: string;
  ended_at: string | null;
  models: string[];
  is_public: boolean;
  url: string | null;
  moderation_status: string;
  media_status: string;
  likes: number;
  votes: number;
  views: number;
  charged: number;
  own_key: boolean;
  via_token: boolean;
  error: string | null;
}

export interface Page<T> {
  total: number;
  rows: T[];
}

export type CreditKind = 'adjustment' | 'bonus' | 'refund';

export interface CreditChangeOut {
  transaction_id: string;
  balance_before: number;
  balance_after: number;
  duplicate: boolean;
}

// --- debates and moderation (routes_debates.py) ------------------------------------------------

export type DebateSort = 'created' | 'likes' | 'views' | 'cost' | 'charged' | 'turns';

export interface DebateFilters {
  q?: string;
  status?: string;
  active?: boolean;
  failed?: boolean;
  moderation?: string;
  media?: string;
  public?: boolean;
  own_key?: boolean;
  via_token?: boolean;
  model?: string;
  user_id?: string;
  created_from?: string;
  created_to?: string;
}

export interface DebateOwner {
  id: string;
  email: string;
  display_name: string;
}

export interface AdminDebateRow {
  id: string;
  title: string;
  owner: DebateOwner | null;
  status: string;
  models: string[];
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  turns: number;
  /** Provider cost on the system keys; null without the money permission. */
  cost: number | null;
  charged: number | null;
  own_key: boolean;
  via_token: boolean;
  is_public: boolean;
  url: string | null;
  moderation_status: string;
  media_status: string;
  views: number;
  likes: number;
  votes: number;
  error: string | null;
}

export interface AdminDebateList {
  total: number;
  limit: number;
  offset: number;
  rows: AdminDebateRow[];
}

export interface AdminTurn {
  seq_index: number;
  round_id: string;
  turn_type: string;
  speaker_name: string;
  model_used: string;
  text: string;
  error: string | null;
  created_at: string | null;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  duration_ms: number | null;
  ttft_ms: number | null;
  error_kind: string | null;
  visuals_status: string;
  scenes: number;
  checks: Record<string, number>;
  disputes: number;
}

export interface UsageByPurpose {
  purpose: string;
  key_owner: string;
  calls: number;
  failures: number;
  cost: number;
}

export interface RecoveryState {
  debate_beat: boolean;
  media_beat: boolean;
  debate_attempts: number;
  media_attempts: number;
  stop_flag: boolean;
  provider_key: boolean;
  tts_key: boolean;
}

/** The topic a debate is a version of (backend services/motions). */
export interface AdminDebateMotion {
  slug: string;
  /** The first public version's text; null while none is public. */
  title: string | null;
  public_versions: number;
  /** Versions in all, private ones and drafts too. */
  debates: number;
  /** The topic page on the site, while a version is public. */
  url: string | null;
}

export interface AdminDebateCard {
  debate: AdminDebateRow;
  motion: AdminDebateMotion | null;
  topic: string;
  config: Record<string, unknown>;
  totals: Record<string, unknown>;
  turns: AdminTurn[];
  verdict: Record<string, unknown>;
  moderation: Record<string, unknown>;
  wants_public: boolean;
  media: Record<string, unknown> & { status: string };
  cover: AdminCover;
  recovery: RecoveryState;
  usage: UsageByPurpose[] | null;
  ledger: AdminLedgerRow[] | null;
  refundable: number | null;
  /** The turn a resume starts from (0-based), when the debate can be resumed. */
  resume_from: number | null;
  audit: AuditEntry[];
  views: AdminDebateViews;
}

/** A debate's views: the counter, by source (its page / players elsewhere) and the sites that
 *  embed it. `untracked`: views counted before sources were kept. */
export interface AdminDebateViews {
  total: number;
  sources: { source: ViewSource; page: number; embed: number }[];
  untracked: number;
  last_7d: number;
  embeds: EmbedSite[];
}

/** A debate's AI cover in the console (backend services/media/cover.py). */
export interface AdminCoverVersion {
  id: string;
  /** 768 px wide, through the console's files route. */
  url: string;
  full_url: string;
  hook: string;
  source: 'auto' | 'owner' | 'admin' | string;
  cost_usd: number;
  tries: number;
  own_key: boolean;
  created_at: string | null;
}

export interface AdminCover {
  status: 'none' | 'queued' | 'running' | 'ready' | 'error';
  error: string | null;
  /** The version shown; null: the markup cover. */
  current: string | null;
  versions: AdminCoverVersion[];
}

export interface ModerationItem {
  id: string;
  title: string;
  owner: DebateOwner | null;
  models: string[];
  created_at: string;
  ended_at: string | null;
  reason: string | null;
  source: string | null;
  checked_at: string | null;
  publish_requested: boolean;
  /** Its AI cover (console URL), when it has one. */
  cover_url: string | null;
}

export interface ModerationDecision {
  debate_id: string | null;
  title: string | null;
  action: string;
  actor_email: string | null;
  reason: string | null;
  created_at: string;
}

export interface ModerationQueue {
  flagged: ModerationItem[];
  recent: ModerationDecision[];
}

export interface ActionOut {
  status: string;
  message: string;
}

export interface RefundOut {
  transaction_id: string;
  amount: number;
  balance_after: number;
  duplicate: boolean;
}

// --- trending (routes_trending.py) ------------------------------------------------------------

export interface TrendingBatchRow {
  id: string;
  created_at: string;
  /** The writer, and the model that reviewed the lists (the same one before 1.6). */
  model: string;
  review_model: string;
  topic_count: number;
  hidden: number;
  cost_usd: number;
  current: boolean;
  feeds_ok: number | null;
  feeds_total: number | null;
  headlines_fresh: number | null;
  headlines_blocked: number | null;
  headlines_sent: number | null;
  topics_asked: number | null;
  dropped: number;
  /** Each format's list (empty for batches from before format lists). */
  formats: TrendingFormatList[];
}

export interface TrendingFormatList {
  format: string;
  asked: number | null;
  kept: number | null;
  /** The list failed: its format keeps an older batch's list. */
  error: string | null;
}

export interface TrendingTopicRow {
  id: string;
  /** Whose list it is on ("debate", "rap_battle"). */
  format: string;
  /** 1 = hottest within that list. */
  rank: number;
  label: string;
  question: string;
  brief: string;
  category: string;
  heat: number;
  outlets: number;
  sources: { title?: string; url?: string; outlet?: string; published_at?: string }[];
  is_hidden: boolean;
}

export interface TrendingBatchCard {
  batch: TrendingBatchRow;
  topics: TrendingTopicRow[];
  dropped: { question?: string; reason?: string; format?: string }[];
  blocked: { title?: string; term?: string }[];
}

// --- system (routes_system.py) ----------------------------------------------------------------

export interface JobSummary {
  id: string;
  queue: string;
  func: string;
  debate_id: string | null;
  status: string | null;
  enqueued_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  /** The end of the traceback. */
  error: string | null;
}

export interface QueueStats {
  name: string;
  waiting: number;
  started: number;
  failed: number;
  scheduled: number;
  deferred: number;
  finished: number;
}

export interface WorkerInfo {
  name: string;
  hostname: string | null;
  pid: number | null;
  queues: string[];
  state: string;
  current_job: JobSummary | null;
  last_heartbeat: string | null;
  birth: string | null;
  successful: number;
  failed: number;
  working_seconds: number;
}

export interface SchedulerInfo {
  name: string;
  hostname: string | null;
  pid: number | null;
  started_at: string | null;
  last_heartbeat: string | null;
}

export interface CronJobInfo {
  name: string;
  interval_seconds: number | null;
  last_enqueued_at: string | null;
  recent: JobSummary[];
}

export interface QueuesOut {
  queues: QueueStats[];
  workers: WorkerInfo[];
  schedulers: SchedulerInfo[];
  cron_jobs: CronJobInfo[];
  failed_jobs: JobSummary[];
}

export interface RunInfo {
  debate_id: string;
  title: string;
  owner_email: string | null;
  kind: 'debate' | 'media';
  status: string;
  step: string;
  age_seconds: number;
  heartbeat: boolean;
  waiting: boolean;
  attempts: number;
  stuck: boolean;
}

export interface FairShareUser {
  user_id: string;
  email: string | null;
  kind: 'debate' | 'media';
  active: number | null;
  refusals: number;
  last_refused_at: string | null;
}

export interface LimitsOut {
  free_per_minute: number;
  free_used_this_minute: number;
  free_requests_24h: number;
  free_rate_limited_24h: number;
  free_daily_cap: number;
  max_debates_per_user: number;
  max_media_per_user: number;
  debate_create_rate_limit: number;
  login_rate_limit: number;
  at_limit_now: FairShareUser[];
  refused_24h: FairShareUser[];
}

export interface ProvidersOut {
  checked_at: string;
  openrouter: {
    balance?: number;
    total_credits?: number;
    total_usage?: number;
    error?: string;
    key?: { label?: string | null; limit?: number | null; limit_remaining?: number | null; usage?: number | null; usage_daily?: number | null; is_free_tier?: boolean | null };
  };
  elevenlabs: { configured: boolean; ok?: boolean; reason?: string | null; tier?: string; used?: number; limit?: number; resets_at?: number | null };
  payments: { mode: string; currency: string; topup_amounts: number[]; signup_bonus_usd: number; credit_markup: number; min_debate_charge_usd: number; tts_price_per_1k_chars: number; music_price_per_min: number };
}

export interface MediaDir {
  name: string;
  bytes: number;
  files: number;
  title: string | null;
}

export interface HealthOut {
  version: string;
  environment: string;
  alembic_current: string | null;
  alembic_head: string | null;
  database: { ok: boolean; latency_ms: number | null; bytes: number | null; connections: number | null; tables: { name: string; bytes: number; rows: number }[]; error?: string | null };
  redis: { ok: boolean; latency_ms: number | null; version: string | null; uptime_seconds: number | null; used_memory: number | null; peak_memory: number | null; max_memory: number | null; keys: number | null; error?: string | null };
  media: {
    root: string;
    disk_total: number | null;
    disk_used: number | null;
    disk_free: number | null;
    bytes: number;
    dirs: number;
    heaviest: MediaDir[];
    orphans: MediaDir[];
    orphan_bytes: number;
    scanned_at: string;
  };
  backup: { at?: string; file?: string; bytes?: number; remote?: string } | null;
  config: { name: string; value: string }[];
}

// --- finance and models (routes_finance.py) ----------------------------------------------------

export type FinancePeriod = '30d' | '90d' | '12m' | 'all';
export type ModelsPeriod = '30d' | '90d' | 'all';

export interface MoneyRow {
  topups: number;
  bonuses: number;
  refunds: number;
  adjustments_in: number;
  adjustments_out: number;
  charged_models: number;
  charged_voices: number;
  charged_pictures: number;
  charged_music: number;
  charged_cover: number;
  charged: number;
  /** System-key cost of what users pay for. */
  cost_billed: number;
  /** System-key cost nobody pays us for (director, sketches, checks, trending…). */
  cost_unbilled: number;
  cost_openrouter: number;
  cost_elevenlabs: number;
  cost: number;
  margin: number;
  markup: number | null;
}

export interface FinancePoint extends MoneyRow {
  t: string;
}

export interface TopAccount {
  user_id: string;
  email: string;
  amount: number;
}

export interface StripeReconciliation {
  configured: boolean;
  error?: string | null;
  sessions: number;
  paid_total: number;
  credited: number;
  credited_total: number;
  missing: { id: string; email: string | null; amount: number; created: string }[];
  unmatched: string[];
}

export interface FinanceOut {
  period: FinancePeriod;
  bucket: 'day' | 'week' | 'month';
  start: string;
  end: string;
  totals: MoneyRow;
  series: FinancePoint[];
  cost_by_purpose: Record<string, number>;
  cost_tracked_since: string | null;
  liabilities: number;
  negative_balances: number;
  negative_total: number;
  top_payers: TopAccount[];
  top_spenders: TopAccount[];
  stripe: StripeReconciliation;
}

export interface ModelRow {
  model: string;
  name: string;
  is_free: boolean;
  in_catalogue: boolean;
  /** Turned off on the Settings page (hidden from the wizard). */
  disabled?: boolean;
  debates: number;
  tries: number;
  failure_rate: number | null;
  errors: Record<string, number>;
  own_key_tries: number;
  duration_p50_ms: number | null;
  duration_p90_ms: number | null;
  ttft_p50_ms: number | null;
  ttft_p90_ms: number | null;
  cost_per_turn: number | null;
  avg_tokens_out: number | null;
  judge_wins: number;
  judge_contests: number;
  audience_wins: number;
  audience_contests: number;
  claims_checked: number;
  claims_verified: number;
  claims_disputed: number;
  router_pins: number;
}

// --- audit log (backend/app/schemas/admin.py AuditQuery …) ------------------------------------

export type AuditTab = 'all' | 'security';

export interface AuditQuery {
  tab?: AuditTab;
  q?: string;
  actor?: string;
  /** Exact, or a prefix ending in "." ("auth."). */
  action?: string;
  target_type?: string;
  target_id?: string;
  ok?: boolean;
  created_from?: string;
  created_to?: string;
  limit?: number;
  offset?: number;
}

export interface AuditPage {
  total: number;
  limit: number;
  offset: number;
  rows: AuditEntry[];
}

export interface FacetCount {
  value: string;
  count: number;
}

export interface AuditFacets {
  actions: FacetCount[];
  actors: FacetCount[];
  target_types: FacetCount[];
}

/** The last 7 days of console security events. */
export interface SecuritySummary {
  sign_ins: number;
  failures: number;
  locks: number;
  recovery_codes_used: number;
  addresses: number;
  last_failure: AuditEntry | null;
}

// --- levers and alerts ---------------------------------------------------------------------------

export type LeverKind = 'bool' | 'int' | 'float' | 'factor' | 'text' | 'models' | 'model' | 'lengths' | 'alerts' | 'choice';

export type LeverKey =
  | 'registration_open'
  | 'maintenance'
  | 'maintenance_message'
  | 'disabled_models'
  | 'signup_bonus_usd'
  | 'free_models_per_minute'
  | 'max_active_debates_per_user'
  | 'max_active_media_per_user'
  | 'muted_alerts'
  | 'free_verdict_model'
  | 'free_debates_per_day'
  | 'free_max_rounds'
  | 'free_max_debaters'
  | 'free_lengths'
  | 'credit_markup'
  | 'min_debate_charge_usd'
  | 'tts_price_per_1k_chars'
  | 'music_price_per_min'
  | 'ai_covers'
  | 'trending_daily_topics'
  | 'trending_shown_topics'
  | 'topic_model'
  | 'topic_review_model'
  | 'analytics_enabled'
  | 'analytics_ip_days';

export type LeverValue = boolean | number | string | string[];

export interface Lever {
  key: LeverKey;
  kind: LeverKind;
  value: LeverValue;
  /** The env setting (what a reset goes back to). */
  default: LeverValue;
  overridden: boolean;
  minimum: number | null;
  maximum: number | null;
  /** Kind "choice": the values it takes. */
  choices: string[] | null;
  updated_at: string | null;
  updated_by: string | null;
}

export type AlertGroup = 'security' | 'people' | 'debates' | 'system';

/** An alert kind the console can mute (backend services/alert_events). */
export interface AlertEvent {
  kind: string;
  group: AlertGroup;
  label: string;
  hint: string;
  /** Sent when it happens; otherwise found by the periodic check. */
  at_once: boolean;
}

export interface SettingsOut {
  levers: Lever[];
  /** OpenRouter's catalogue (the wizard's model picker), plus models the levers name that left it. */
  models: ModelInfo[];
  /** What `muted_alerts` can hold. */
  alert_events: AlertEvent[];
  /** How soon every server process sees a change. */
  cache_seconds: number;
}

export type AlertSeverity = 'critical' | 'warning' | 'info';

export interface AlertEntry {
  at: string;
  kind: string;
  severity: AlertSeverity;
  title: string;
  detail: string;
  path: string | null;
  sent: boolean;
  error: string | null;
}

export interface AlertsOut {
  /** ALERT_TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID are set. */
  configured: boolean;
  check_every_seconds: number;
  recent: AlertEntry[];
}

// --- audience (visits of the site; backend services/admin/audience.py) -------------------------

export interface AudienceTiles {
  visitors: Tile;
  visits: Tile;
  pageviews: Tile;
  /** Average time in front per visit. */
  engaged_ms: Tile;
  /** One page and under 10 s. */
  bounce_rate: Tile;
  new_visitors: Tile;
  signups: Tile;
  online: number;
}

export interface AudiencePoint {
  t: string;
  visitors: number;
  visits: number;
  sources: Record<string, number>;
}

/** One line of a breakdown: `key` is what it groups by, `label` a second key where there is one. */
export interface AudienceRow {
  key: string;
  label: string | null;
  visits: number;
  visitors: number;
  engaged_ms: number | null;
  bounce_rate: number | null;
  signups: number;
}

export interface AudiencePage {
  path: string;
  views: number;
  visitors: number;
  engaged_ms: number | null;
  title: string | null;
}

export interface AudienceCampaign {
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  visits: number;
  visitors: number;
  signups: number;
}

export interface AudienceVideo {
  debate_id: string;
  title: string;
  path: string | null;
  plays: number;
  visitors: number;
  finished: number;
}

export interface FunnelStep {
  key: string;
  label: string;
  visitors: number;
}

export interface GeoDatabase {
  available: boolean;
  updated_at: string | null;
  release: string | null;
  attribution: string | null;
}

export interface Audience {
  period: OverviewPeriod;
  start: string;
  end: string;
  previous_start: string | null;
  bucket: 'hour' | 'day' | 'week';
  generated_at: string;
  timezone: string;
  data_since: string | null;
  tiles: AudienceTiles;
  series: AudiencePoint[];
  sources: AudienceRow[];
  referrers: AudienceRow[];
  campaigns: AudienceCampaign[];
  countries: AudienceRow[];
  regions: AudienceRow[];
  cities: AudienceRow[];
  landing: AudienceRow[];
  exits: AudienceRow[];
  pages: AudiencePage[];
  sections: AudienceRow[];
  videos: AudienceVideo[];
  devices: AudienceRow[];
  browsers: AudienceRow[];
  systems: AudienceRow[];
  languages: AudienceRow[];
  screens: AudienceRow[];
  /** Visits started: [Monday … Sunday][hour 0–23] in `timezone`. */
  hours: number[][];
  funnel: FunnelStep[];
  actions: AudienceRow[];
  /** key = verdict; every visit of the period, bots included. */
  verdicts: AudienceRow[];
  /** Bots and AI agents are in the other numbers. */
  bots: boolean;
  geo: GeoDatabase;
}

export interface VisitUser {
  id: string;
  email: string;
  display_name: string;
}

export interface VisitRow {
  id: string;
  visitor_id: string;
  started_at: string;
  last_at: string;
  ip: string | null;
  country: string | null;
  region: string | null;
  city: string | null;
  source: string;
  referrer_host: string | null;
  utm_campaign: string | null;
  landing: string;
  exit_path: string;
  pageviews: number;
  actions: number;
  engaged_ms: number;
  device: string;
  browser: string | null;
  os: string | null;
  new_visitor: boolean;
  staff: boolean;
  /** A person, a bot or an AI agent (backend audience/bots.py). */
  verdict: VisitVerdict;
  /** Automation points minus person points, within ±100. */
  bot_score: number;
  user: VisitUser | null;
}

export type VisitVerdict = 'human' | 'likely_human' | 'unclear' | 'suspect' | 'bot' | 'agent';
/** A verdict, or a group: people = human + likely_human, bots = bot + agent. */
export type VisitVerdictFilter = VisitVerdict | 'people' | 'bots';

export type VisitSort = 'started' | 'engaged' | 'pageviews' | 'actions';

export interface VisitListQuery {
  period?: OverviewPeriod;
  q?: string;
  source?: string;
  country?: string;
  device?: 'desktop' | 'mobile' | 'tablet';
  signed_in?: boolean;
  new_visitor?: boolean;
  action?: string;
  verdict?: VisitVerdictFilter;
  staff?: boolean;
  sort?: VisitSort;
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

export interface VisitList {
  items: VisitRow[];
  total: number;
}

export interface VisitEvent {
  at: string;
  kind: 'page' | 'action';
  name: string;
  label: string;
  path: string;
  engaged_ms: number;
  debate_id: string | null;
  debate_title: string | null;
  props: Record<string, unknown>;
}

export interface BotReason {
  code: string;
  label: string;
  /** > 0 towards automation, < 0 towards a person. */
  points: number;
  detail: string | null;
}

export interface VisitDetail extends VisitRow {
  user_agent: string | null;
  referrer: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  ref: string | null;
  screen: string | null;
  language: string | null;
  timezone: string | null;
  /** The IP's network operator, and whether it is a data centre or a relay. */
  network: string | null;
  network_kind: 'hosting' | 'relay' | null;
  reasons: BotReason[];
  /** What the page counted and said: c = input counts, env = browser, srv = request headers. */
  signals: { c?: Record<string, number>; env?: Record<string, string | number | boolean>; srv?: Record<string, string | boolean> };
}

export interface VisitorSummary {
  visitor_id: string;
  first_seen: string;
  last_seen: string;
  visits: number;
  pageviews: number;
  engaged_ms: number;
  accounts: VisitUser[];
}

export interface SharedAddress {
  ip: string;
  user: VisitUser;
  visits: number;
  last_at: string;
}

export interface VisitCard {
  visit: VisitDetail;
  events: VisitEvent[];
  visitor: VisitorSummary;
  visitor_visits: VisitRow[];
  same_ip: SharedAddress[];
}

export interface AddressRow {
  ip: string;
  country: string | null;
  region: string | null;
  city: string | null;
  visits: number;
  first_at: string;
  last_at: string;
}

export interface UserVisits {
  visits: VisitRow[];
  total: number;
  engaged_ms: number;
  pageviews: number;
  first: VisitRow | null;
  addresses: AddressRow[];
  shared: SharedAddress[];
}

export interface LiveVisits {
  visits: VisitRow[];
  generated_at: string;
}
