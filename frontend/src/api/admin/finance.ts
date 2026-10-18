import { adminApi } from './client';
import type { FinanceOut, FinancePeriod, ModelRow, ModelsPeriod } from './types';

export const getFinance = (period: FinancePeriod) => adminApi.get<FinanceOut>('/finance', { params: { period } }).then((r) => r.data);

/** The period's series as CSV (needs sudo). */
export const exportFinance = (period: FinancePeriod) =>
  adminApi.post<Blob>('/finance/export', null, { params: { period }, responseType: 'blob' }).then((r) => {
    const name = /filename="([^"]+)"/.exec(String(r.headers['content-disposition'] ?? ''))?.[1] ?? 'finance.csv';
    return { blob: r.data, name };
  });

export const getModels = (period: ModelsPeriod) =>
  adminApi.get<{ period: ModelsPeriod; rows: ModelRow[] }>('/models', { params: { period } }).then((r) => r.data.rows);
