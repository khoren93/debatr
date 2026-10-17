import { api } from './client';
import type { BillingConfig, CheckoutResponse, ConfirmResponse, Transaction, Usage } from './types';

export const getBillingConfig = () => api.get<BillingConfig>('/billing/config').then((r) => r.data);

export const createCheckout = (amountUsd: number) =>
  api.post<CheckoutResponse>('/billing/checkout', { amount_usd: amountUsd }).then((r) => r.data);

export const confirmCheckout = (sessionId: string) =>
  api.get<ConfirmResponse>('/billing/confirm', { params: { session_id: sessionId } }).then((r) => r.data);

export const listTransactions = (limit = 50, offset = 0) =>
  api.get<Transaction[]>('/billing/transactions', { params: { limit, offset } }).then((r) => r.data);

/** The whole ledger as CSV text, with the server's file name. */
export const exportTransactions = () =>
  api.get<string>('/billing/transactions.csv', { responseType: 'text' }).then((r) => {
    const disposition = String(r.headers['content-disposition'] ?? '');
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? 'ledger.csv';
    return { text: r.data, name };
  });

export const getUsage = () => api.get<Usage>('/billing/usage').then((r) => r.data);
