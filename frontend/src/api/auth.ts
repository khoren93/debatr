import { api } from './client';
import type { User } from './types';

export const getMe = () => api.get<User | null>('/auth/me').then((r) => r.data);

export const login = (email: string, password: string) =>
  api.post<User>('/auth/login', { email, password }).then((r) => r.data);

export const register = (email: string, password: string, displayName?: string) =>
  api.post<User>('/auth/register', { email, password, display_name: displayName || undefined }).then((r) => r.data);

export const logout = () => api.post('/auth/logout').then(() => undefined);

export const updateProfile = (body: { display_name?: string; avatar_seed?: string }) =>
  api.patch<User>('/auth/me', body).then((r) => r.data);

export const changePassword = (currentPassword: string, newPassword: string) =>
  api.post('/auth/me/password', { current_password: currentPassword, new_password: newPassword }).then(() => undefined);

/** Mail a password reset link (the same answer whether the account exists or not). */
export const forgotPassword = (email: string) => api.post('/auth/password/forgot', { email }).then(() => undefined);

/** Set a new password from a mailed link; signs this browser in. */
export const resetPassword = (token: string, password: string) =>
  api.post<User>('/auth/password/reset', { token, password }).then((r) => r.data);

/** Confirm the email a mailed link went to; `published` = debates that went public with it. */
export const verifyEmail = (token: string) =>
  api.post<{ ok: boolean; published: number }>('/auth/email/verify', { token }).then((r) => r.data);

/** Mail the signed-in account a new confirmation link. */
export const resendConfirmation = () => api.post('/auth/email/resend').then(() => undefined);

export const setOpenRouterKey = (key: string) =>
  api.put<User>('/auth/me/openrouter-key', { key }).then((r) => r.data);

export const removeOpenRouterKey = () => api.delete<User>('/auth/me/openrouter-key').then((r) => r.data);
