import { api } from './client';
import type {
  Audience,
  CreateDebateResponse,
  DebateConfig,
  DebateDetail,
  DebateSummary,
  Estimate,
  PublishResponse,
} from './types';

export const listDebates = (params: { status?: string; q?: string; limit?: number; offset?: number } = {}) =>
  api.get<DebateSummary[]>('/debates', { params: { limit: 200, ...params } }).then((r) => r.data);

export const getDebate = (id: string) => api.get<DebateDetail>(`/debates/${id}`).then((r) => r.data);

/** One view of a public debate whose page came from the server (its loader counts none): a
 *  beacon, so leaving the page does not cancel it. */
export const countView = (id: string) => {
  const url = `${api.defaults.baseURL ?? '/api'}/debates/${id}/view`;
  if (!navigator.sendBeacon?.(url)) void fetch(url, { method: 'POST', keepalive: true, credentials: 'same-origin' }).catch(() => undefined);
};

export const createDebate = (config: DebateConfig) =>
  api.post<CreateDebateResponse>('/debates', config).then((r) => r.data);

export const updateDraft = (id: string, config: DebateConfig) =>
  api.patch<CreateDebateResponse>(`/debates/${id}`, config).then((r) => r.data);

export const startDraft = (id: string, keys: { user_provider_key?: string; user_tts_key?: string } = {}) =>
  api.post<CreateDebateResponse>(`/debates/${id}/start`, keys).then((r) => r.data);

/** Run a failed debate again from the turn that failed (backend services/resume.py). */
export const resumeDebate = (id: string, keys: { user_provider_key?: string; user_tts_key?: string } = {}) =>
  api.post<CreateDebateResponse>(`/debates/${id}/resume`, keys).then((r) => r.data);

export const estimateDebate = (config: DebateConfig) =>
  api.post<Estimate>('/debates/estimate', config).then((r) => r.data);

export const stopDebate = (id: string) =>
  api.post<{ debate_id: string; status: string }>(`/debates/${id}/stop`).then((r) => r.data);

export const deleteDebate = (id: string) => api.delete(`/debates/${id}`).then(() => undefined);

export const publishDebate = (id: string, category: string | null) =>
  api.post<PublishResponse>(`/debates/${id}/publish`, { category }).then((r) => r.data);

export const unpublishDebate = (id: string) =>
  api.delete<PublishResponse>(`/debates/${id}/publish`).then((r) => r.data);

export const reportRender = (id: string, kind: 'long' | 'short') =>
  api.post<{ renders: Record<string, number> }>(`/debates/${id}/renders`, { kind }).then((r) => r.data);

export const setLike = (id: string, liked: boolean) =>
  (liked ? api.put<{ liked: boolean; likes: number }>(`/debates/${id}/like`) : api.delete<{ liked: boolean; likes: number }>(`/debates/${id}/like`)).then((r) => r.data);

export const castVote = (id: string, participantId: string) =>
  api.put<Audience>(`/debates/${id}/vote`, { participant_id: participantId }).then((r) => r.data);

export const retractVote = (id: string) => api.delete<Audience>(`/debates/${id}/vote`).then((r) => r.data);

export const debateStreamUrl = (id: string) => `${api.defaults.baseURL}/debates/${id}/stream`;
