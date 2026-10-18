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
