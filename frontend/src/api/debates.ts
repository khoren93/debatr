import { api, API_BASE } from './client';
import type {
  Audience,
  Cover,
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

/** What a view tells the server (backend routes_reactions.ViewBeacon): where it happened, the
 *  referrer's host (never the whole address), whether it is a navigation inside the site and the
 *  page's `?ref=`. The server turns it into a source (search, social, embed…). */
export interface ViewBeacon {
  place: 'page' | 'embed';
  referrer: string;
  internal: boolean;
  ref: string;
}

/** The host of the page that sent the visitor here ('' without one). */
export const referrerHost = (): string => {
  try {
    return document.referrer ? new URL(document.referrer).hostname : '';
  } catch {
    return '';
  }
};

/** Whether the current page is the one the browser loaded, not a navigation inside the site: only
 *  then does `document.referrer` tell where the visitor came from. */
export const isLandingPage = (): boolean => {
  const entry = performance.getEntriesByType?.('navigation')[0];
  return !entry || entry.name.split('#')[0] === window.location.href.split('#')[0];
};

/** One view of a public debate (reading it through the API counts none): a beacon, so leaving the
 *  page does not cancel it. Plain text, so the browser sends it without a preflight. */
export const countView = (id: string, beacon: ViewBeacon) => {
  const url = `${API_BASE}/debates/${id}/view`;
  const body = JSON.stringify(beacon);
  if (!navigator.sendBeacon?.(url, new Blob([body], { type: 'text/plain' }))) {
    void fetch(url, { method: 'POST', body, headers: { 'Content-Type': 'text/plain' }, keepalive: true, credentials: 'same-origin' }).catch(() => undefined);
  }
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

export const debateStreamUrl = (id: string) => `${API_BASE}/debates/${id}/stream`;

/** A new AI cover version (backend services/media/cover.py); `hook` replaces the art director's. */
export const generateCover = (id: string, body: { hook?: string; user_provider_key?: string } = {}) =>
  api.post<Cover>(`/debates/${id}/cover`, body).then((r) => r.data);

/** Show another cover version (null: the markup cover). */
export const selectCover = (id: string, version: string | null) => api.put<Cover>(`/debates/${id}/cover`, { version }).then((r) => r.data);

export const deleteCoverVersion = (id: string, version: string) => api.delete<Cover>(`/debates/${id}/cover/${version}`).then((r) => r.data);
