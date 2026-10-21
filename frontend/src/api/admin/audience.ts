import { adminApi } from './client';
import type { Audience, LiveVisits, OverviewPeriod, UserVisits, VisitCard, VisitList, VisitListQuery } from './types';

export const getAudience = (period: OverviewPeriod, timezone: string, staff: boolean, refresh = false) =>
  adminApi.get<Audience>('/audience', { params: { period, tz: timezone, staff: staff || undefined, refresh: refresh || undefined } }).then((r) => r.data);

export const getLiveVisits = () => adminApi.get<LiveVisits>('/audience/live').then((r) => r.data);

export const listVisits = (query: VisitListQuery) => adminApi.get<VisitList>('/audience/visits', { params: query }).then((r) => r.data);

export const getVisit = (id: string) => adminApi.get<VisitCard>(`/audience/visits/${encodeURIComponent(id)}`).then((r) => r.data);

export const getUserVisits = (id: string) => adminApi.get<UserVisits>(`/users/${encodeURIComponent(id)}/visits`).then((r) => r.data);
