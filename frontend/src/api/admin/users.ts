import { adminApi } from './client';
import type {
  AdminLedgerRow,
  AdminUserCard,
  AdminUserDebate,
  AdminUserList,
  CreditChangeOut,
  CreditKind,
  Page,
  UserFilters,
  UserSort,
} from './types';

export interface UserListQuery extends UserFilters {
  sort?: UserSort;
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

export const listUsers = (query: UserListQuery) => adminApi.get<AdminUserList>('/users', { params: query }).then((r) => r.data);

/** The filtered list as CSV (needs sudo); resolves to the file and its name. */
export const exportUsers = (query: UserListQuery) =>
  adminApi.post<Blob>('/users/export', null, { params: query, responseType: 'blob' }).then((r) => {
    const disposition = String(r.headers['content-disposition'] ?? '');
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? 'users.csv';
    return { blob: r.data, name };
  });

export const getUserCard = (id: string) => adminApi.get<AdminUserCard>(`/users/${id}`).then((r) => r.data);

export const getUserLedger = (id: string, offset: number, limit = 50) =>
  adminApi.get<Page<AdminLedgerRow>>(`/users/${id}/ledger`, { params: { offset, limit } }).then((r) => r.data);

export const getUserDebates = (id: string, offset: number, limit = 20) =>
  adminApi.get<Page<AdminUserDebate>>(`/users/${id}/debates`, { params: { offset, limit } }).then((r) => r.data);

export const changeCredits = (
  id: string,
  body: { amount: string; kind: CreditKind; reason: string; description?: string; idempotency_key: string },
) => adminApi.post<CreditChangeOut>(`/users/${id}/credits`, body).then((r) => r.data);

export const disableUser = (id: string, body: { reason: string; stop_debates: boolean; revoke_tokens: boolean; unpublish: boolean }) =>
  adminApi
    .post<{ stopped: number; tokens_revoked: number; unpublished: number }>(`/users/${id}/disable`, body)
    .then((r) => r.data);

export const enableUser = (id: string, reason: string) => adminApi.post(`/users/${id}/enable`, { reason }).then(() => undefined);

/** One token, or every token without `tokenId`. Resolves to how many were revoked. */
export const revokeUserTokens = (id: string, reason: string, tokenId?: string) =>
  adminApi.post<{ count: number }>(`/users/${id}/tokens/revoke`, { reason, token_id: tokenId ?? null }).then((r) => r.data.count);

export const removeUserOpenRouterKey = (id: string, reason: string) =>
  adminApi.post(`/users/${id}/openrouter-key/remove`, { reason }).then(() => undefined);

export const signOutUser = (id: string, reason: string) => adminApi.post(`/users/${id}/sign-out`, { reason }).then(() => undefined);

export const setTemporaryPassword = (id: string, reason: string) =>
  adminApi.post<{ temporary_password: string }>(`/users/${id}/temporary-password`, { reason }).then((r) => r.data.temporary_password);

export const deleteUser = (id: string, reason: string, confirmEmail: string) =>
  adminApi.post<{ debates: number }>(`/users/${id}/delete`, { reason, confirm_email: confirmEmail }).then((r) => r.data.debates);
