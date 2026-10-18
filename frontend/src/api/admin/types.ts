// Mirrors backend/app/schemas/admin.py (the admin console API).

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
}

export interface AdminLoginOut {
  next: 'totp' | 'enroll';
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
}

export interface OverviewMoney {
  topups: number;
  bonuses: number;
  refunds: number;
  adjustments: number;
  charged: Record<'models' | 'voices' | 'pictures', number>;
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
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  reason: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip: string | null;
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

export interface AdminDebateCard {
  debate: AdminDebateRow;
  topic: string;
  config: Record<string, unknown>;
  totals: Record<string, unknown>;
  turns: AdminTurn[];
  verdict: Record<string, unknown>;
  moderation: Record<string, unknown>;
  wants_public: boolean;
  media: Record<string, unknown> & { status: string };
  recovery: RecoveryState;
  usage: UsageByPurpose[] | null;
  ledger: AdminLedgerRow[] | null;
  refundable: number | null;
  /** The turn a resume starts from (0-based), when the debate can be resumed. */
  resume_from: number | null;
  audit: AuditEntry[];
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
  model: string;
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
}

export interface TrendingTopicRow {
  id: string;
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
  dropped: { question?: string; reason?: string }[];
  blocked: { title?: string; term?: string }[];
}
