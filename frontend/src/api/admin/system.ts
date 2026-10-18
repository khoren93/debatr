import { adminApi } from './client';
import type { ActionOut, HealthOut, LimitsOut, ProvidersOut, QueuesOut, RunInfo } from './types';

export const getQueues = () => adminApi.get<QueuesOut>('/system/queues').then((r) => r.data);

export const failedJobAction = (id: string, action: 'requeue' | 'delete', reason: string) =>
  adminApi.post<ActionOut>(`/system/jobs/${id}/${action}`, { reason }).then((r) => r.data);

export const getRuns = () => adminApi.get<{ runs: RunInfo[] }>('/system/runs').then((r) => r.data.runs);

export const recoverRun = (debateId: string, kind: RunInfo['kind'], reason: string) =>
  adminApi.post<ActionOut>(`/system/runs/${debateId}/recover`, { kind, reason }).then((r) => r.data);

export const getLimits = () => adminApi.get<LimitsOut>('/system/limits').then((r) => r.data);

export const getProviders = (refresh = false) =>
  adminApi.get<ProvidersOut>('/system/providers', { params: { refresh: refresh || undefined } }).then((r) => r.data);

export const getHealth = (refresh = false) =>
  adminApi.get<HealthOut>('/system/health', { params: { refresh: refresh || undefined } }).then((r) => r.data);

export const deleteOrphans = (names: string[], reason: string) =>
  adminApi.post<{ deleted: number; bytes: number; skipped: string[] }>('/system/media/orphans/delete', { names, reason }).then((r) => r.data);
