import { api } from './client';
import type { FormatId, TopicIdeas, TrendingArchive, TrendingTopics } from './types';

/** Topics made from today's news for a format (its own list or the debate's), hottest first. */
export const getTrendingTopics = (format: FormatId) => api.get<TrendingTopics>('/topics/trending', { params: { format } }).then((r) => r.data);

/** Topics of earlier batches that hold every word of `q` (the list shows only the newest batch). */
export const searchTopicArchive = (format: FormatId, q: string) =>
  api.get<TrendingArchive>('/topics/trending/search', { params: { format, q } }).then((r) => r.data);

/** Topics for a format written by AI from the user's own words (free, limited per hour). */
export const getTopicIdeas = (text: string, format: FormatId, language: string) =>
  api.post<TopicIdeas>('/topics/ideas', { text, format, language }).then((r) => r.data);
