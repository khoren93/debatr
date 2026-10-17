import { api } from './client';
import type { TrendingTopics } from './types';

/** Debate topics made from today's news (newest batch, hottest first). */
export const getTrendingTopics = () => api.get<TrendingTopics>('/topics/trending').then((r) => r.data);
