import { adminApi } from './client';
import type { MailLetter, MailPage, MailQuery, MailStatusSummary } from './types';

export const listMail = (query: MailQuery) => adminApi.get<MailPage>('/mail', { params: query }).then((r) => r.data);

export const getMailStatus = () => adminApi.get<MailStatusSummary>('/mail/status').then((r) => r.data);

/** Sends a test letter now and answers with what the relay said. */
export const sendTestMail = (to: string) => adminApi.post<MailLetter>('/mail/test', { to }).then((r) => r.data);
