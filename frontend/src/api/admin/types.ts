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
