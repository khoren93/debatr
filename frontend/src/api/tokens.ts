import { api } from './client';
import type { ApiToken, ApiTokenCreated, DeviceRequest, NewApiToken } from './types';

export const listTokens = () => api.get<ApiToken[]>('/auth/tokens').then((r) => r.data);

export const createToken = (body: NewApiToken) => api.post<ApiTokenCreated>('/auth/tokens', body).then((r) => r.data);

export const revokeToken = (id: string) => api.delete(`/auth/tokens/${encodeURIComponent(id)}`).then(() => undefined);

const devicePath = (code: string) => `/auth/device/${encodeURIComponent(code)}`;

export const getDeviceRequest = (code: string) => api.get<DeviceRequest>(devicePath(code)).then((r) => r.data);

export const approveDevice = (code: string, body: NewApiToken) =>
  api.post<ApiToken>(`${devicePath(code)}/approve`, body).then((r) => r.data);

export const denyDevice = (code: string) => api.post(`${devicePath(code)}/deny`).then(() => undefined);
