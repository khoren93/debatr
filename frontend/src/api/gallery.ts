import { api } from './client';
import type { DebateDetail, GalleryGroup, GalleryPeriod, GalleryResponse, GallerySort, Leaderboard } from './types';

export interface GalleryQuery {
  category?: string;
  q?: string;
  /** Only debates this model argued in. */
  model?: string;
  /** Only debates voiced by ElevenLabs. */
  premium_voices?: boolean;
  sort?: GallerySort;
  /** Publication window for `sort=top`. */
  period?: GalleryPeriod;
  /** `motion`: one card per topic (its best version under these filters). */
  group?: GalleryGroup;
  limit?: number;
  offset?: number;
}

export const listGallery = (params: GalleryQuery = {}) => api.get<GalleryResponse>('/gallery', { params }).then((r) => r.data);

export const getPublicDebate = (slug: string) =>
  api.get<DebateDetail>(`/gallery/${encodeURIComponent(slug)}`).then((r) => r.data);

export const getLeaderboard = () => api.get<Leaderboard>('/gallery/leaderboard').then((r) => r.data);
