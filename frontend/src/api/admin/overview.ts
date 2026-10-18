import { adminApi } from './client';
import type { Overview, OverviewPeriod } from './types';

export const getOverview = (period: OverviewPeriod, refresh = false) =>
  adminApi.get<Overview>('/overview', { params: { period, refresh: refresh || undefined } }).then((r) => r.data);
