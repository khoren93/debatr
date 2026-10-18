import { api } from './client';
import type { SiteStatus } from './types';

export const getSiteStatus = () => api.get<SiteStatus>('/status').then((r) => r.data);
