import { adminApi } from './client';
import type { AdminLoginOut, AdminMe, AdminPasskey, AdminSessionRow, AdminSignedIn, EnrollStartOut, PasskeyOptions } from './types';

export const getAdminMe = () => adminApi.get<AdminMe>('/auth/me').then((r) => r.data);

export const adminLogin = (email: string, password: string) =>
  adminApi.post<AdminLoginOut>('/auth/login', { email, password }).then((r) => r.data);

export const verifyAdminCode = (body: { code?: string; recovery_code?: string }) =>
  adminApi.post<AdminSignedIn>('/auth/totp', body).then((r) => r.data);

export const startEnrollment = (enrollmentCode: string) =>
  adminApi.post<EnrollStartOut>('/auth/enroll/start', { enrollment_code: enrollmentCode }).then((r) => r.data);

export const confirmEnrollment = (code: string) =>
  adminApi.post<AdminSignedIn>('/auth/enroll/confirm', { code }).then((r) => r.data);

export const adminLogout = () => adminApi.post('/auth/logout').then(() => undefined);

export const adminLogoutEverywhere = () => adminApi.post('/auth/logout-all').then(() => undefined);

export const listAdminSessions = () => adminApi.get<AdminSessionRow[]>('/auth/sessions').then((r) => r.data);

export const revokeAdminSession = (id: string) => adminApi.delete(`/auth/sessions/${id}`).then(() => undefined);

export const confirmSudo = (code: string) =>
  adminApi.post<{ sudo_until: string }>('/auth/sudo', { code }).then((r) => r.data);

export const regenerateRecoveryCodes = () =>
  adminApi.post<{ recovery_codes: string[] }>('/auth/recovery-codes').then((r) => r.data);

// --- passkeys (credential = PublicKeyCredential as JSON, see ./webauthn) ----------------------------

export const passkeySignInOptions = () => adminApi.post<PasskeyOptions>('/auth/passkey/options').then((r) => r.data.options);

export const signInWithPasskey = (credential: unknown) =>
  adminApi.post<AdminSignedIn>('/auth/passkey', { credential }).then((r) => r.data);

export const listPasskeys = () => adminApi.get<AdminPasskey[]>('/auth/passkeys').then((r) => r.data);

/** Needs sudo. */
export const passkeyAddOptions = () => adminApi.post<PasskeyOptions>('/auth/passkeys/options').then((r) => r.data.options);

export const addPasskey = (name: string, credential: unknown) =>
  adminApi.post<AdminPasskey>('/auth/passkeys', { name, credential }).then((r) => r.data);

/** Needs sudo. */
export const removePasskey = (id: string) => adminApi.delete(`/auth/passkeys/${id}`).then(() => undefined);

export const sudoPasskeyOptions = () => adminApi.post<PasskeyOptions>('/auth/sudo/passkey/options').then((r) => r.data.options);

export const confirmSudoWithPasskey = (credential: unknown) =>
  adminApi.post<{ sudo_until: string }>('/auth/sudo/passkey', { credential }).then((r) => r.data);
