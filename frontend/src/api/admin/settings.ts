import { adminApi } from './client';
import type { AlertsOut, LeverKey, LeverValue, SettingsOut } from './types';

export const getSettings = () => adminApi.get<SettingsOut>('/settings').then((r) => r.data);

/** Needs sudo; resolves to every lever after the change. */
export const changeLever = (key: LeverKey, value: LeverValue, reason: string) =>
  adminApi.put<SettingsOut>(`/settings/${key}`, { value, reason }).then((r) => r.data);

/** Back to the env setting (needs sudo). */
export const resetLever = (key: LeverKey, reason: string) =>
  adminApi.post<SettingsOut>(`/settings/${key}/reset`, { reason }).then((r) => r.data);

export const getAlerts = () => adminApi.get<AlertsOut>('/alerts').then((r) => r.data);

export const sendTestAlert = () => adminApi.post<{ sent: boolean; error: string | null }>('/alerts/test').then((r) => r.data);
