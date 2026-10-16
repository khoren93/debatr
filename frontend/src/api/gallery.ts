import { api } from './client';
import type { DebateDetail, GalleryPeriod, GalleryResponse, GallerySort, Leaderboard } from './types';

export interface GalleryQuery {
  category?: string;
  q?: string;
  /** Only debates this model argued in. */
  model?: string;
  sort?: GallerySort;
  /** Publication window for `sort=top`. */
  period?: GalleryPeriod;
  limit?: number;
  offset?: number;
}

export const listGallery = (params: GalleryQuery = {}) => api.get<GalleryResponse>('/gallery', { params }).then((r) => r.data);

export const getPublicDebate = (slug: string) =>
  api.get<DebateDetail>(`/gallery/${encodeURIComponent(slug)}`).then((r) => r.data);

export const getLeaderboard = () => api.get<Leaderboard>('/gallery/leaderboard').then((r) => r.data);
