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
