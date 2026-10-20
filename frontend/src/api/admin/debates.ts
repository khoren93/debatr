import type { Timeline } from '../timeline';
import { adminApi } from './client';
import type {
  ActionOut,
  AdminDebateCard,
  AdminDebateList,
  DebateFilters,
  DebateSort,
  ModerationQueue,
  Page,
  RefundOut,
  TrendingBatchCard,
  TrendingBatchRow,
} from './types';

export interface DebateListQuery extends DebateFilters {
  sort?: DebateSort;
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

export const listDebates = (query: DebateListQuery) => adminApi.get<AdminDebateList>('/debates', { params: query }).then((r) => r.data);

export const getDebateCard = (id: string) => adminApi.get<AdminDebateCard>(`/debates/${id}`).then((r) => r.data);

/** The debate's media folder through the console: the site's /api/media is closed on the admin
 *  host. Absolute, since Remotion needs full URLs for the audio. */
export const debateFilesBase = (id: string) => `${window.location.origin}/api/admin/debates/${id}/files`;

export const getDebateTimeline = (id: string) => adminApi.get<Timeline>(`/debates/${id}/files/timeline.json`).then((r) => r.data);

export type DebateAction = 'stop' | 'resume' | 'recount' | 'delete' | 'approve' | 'reject' | 'publish' | 'unpublish';

/** A change to the debate with its reason (kept in the audit log). */
export const debateAction = (id: string, action: DebateAction, reason: string) =>
  adminApi.post<ActionOut>(`/debates/${id}/${action}`, { reason }).then((r) => r.data);

/** Move the debate into the topic named by a link, id or slug; no target = a topic of its own;
 *  `whole` merges its entire topic into the target. */
export const moveDebateMotion = (id: string, body: { reason: string; target?: string; whole: boolean }) =>
  adminApi.post<ActionOut>(`/debates/${id}/motion`, body).then((r) => r.data);

export const rebuildDebateMedia = (id: string, reason: string, force: boolean) =>
  adminApi.post<ActionOut>(`/debates/${id}/media`, { reason, force }).then((r) => r.data);

/** A new AI cover version on the system key, free for the owner. */
export const regenerateDebateCover = (id: string, reason: string, hook?: string) =>
  adminApi.post<ActionOut>(`/debates/${id}/cover`, { reason, hook: hook || undefined }).then((r) => r.data);

/** Show another cover version (null: the markup cover). */
export const selectDebateCover = (id: string, reason: string, version: string | null) =>
  adminApi.post<ActionOut>(`/debates/${id}/cover/select`, { reason, version }).then((r) => r.data);

export const refundDebate = (id: string, body: { reason: string; amount?: string; idempotency_key: string }) =>
  adminApi.post<RefundOut>(`/debates/${id}/refund`, body).then((r) => r.data);

export const getModerationQueue = () => adminApi.get<ModerationQueue>('/moderation').then((r) => r.data);

export const listTrendingBatches = (offset: number, limit = 20) =>
  adminApi.get<Page<TrendingBatchRow>>('/trending/batches', { params: { offset, limit } }).then((r) => r.data);

export const getTrendingBatch = (id: string) => adminApi.get<TrendingBatchCard>(`/trending/batches/${id}`).then((r) => r.data);

export const setTopicHidden = (id: string, hidden: boolean) =>
  adminApi.post<ActionOut>(`/trending/topics/${id}/${hidden ? 'hide' : 'show'}`).then((r) => r.data);

export const buildTrendingNow = () => adminApi.post<ActionOut>('/trending/build').then((r) => r.data);
