import { api } from './client';
import type { FormatId, TopicIdeas, TrendingTopics } from './types';

/** Topics made from today's news for a format (its own list or the debate's), hottest first. */
export const getTrendingTopics = (format: FormatId) => api.get<TrendingTopics>('/topics/trending', { params: { format } }).then((r) => r.data);

/** Topics for a format written by AI from the user's own words (free, limited per hour). */
export const getTopicIdeas = (text: string, format: FormatId, language: string) =>
  api.post<TopicIdeas>('/topics/ideas', { text, format, language }).then((r) => r.data);
