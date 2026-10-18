import { adminApi } from './client';
import type { AuditFacets, AuditPage, AuditQuery, SecuritySummary } from './types';

export const listAudit = (query: AuditQuery) => adminApi.get<AuditPage>('/audit', { params: query }).then((r) => r.data);

export const getAuditFacets = () => adminApi.get<AuditFacets>('/audit/facets').then((r) => r.data);

export const getSecuritySummary = () => adminApi.get<SecuritySummary>('/audit/security').then((r) => r.data);
