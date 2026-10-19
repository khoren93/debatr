import { api } from './client';
import type { MotionPage, MotionSuggestions } from './types';

/** A topic and its public versions (`/t/:slug`); a merged topic answers with the one it went into. */
export const getMotion = (slug: string) => api.get<MotionPage>(`/motions/${encodeURIComponent(slug)}`).then((r) => r.data);

export interface SuggestQuery {
  topic: string;
  language: string;
  /** The debate being remixed: a translation of it stays in its topic. */
  remix_of?: string;
}

/** The topic this text would join and similar topics (only topics with public versions). */
export const suggestMotions = (params: SuggestQuery) => api.get<MotionSuggestions>('/motions/suggest', { params }).then((r) => r.data);
