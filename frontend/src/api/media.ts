import { api } from './client';
import type { Timeline } from './timeline';
import type {
  DebateMedia,
  GenerateMediaRequest,
  MediaCapabilities,
  TTSProviderName,
  VoicesResponse,
} from './types';

export const getMediaCapabilities = () =>
  api.get<MediaCapabilities>('/media/capabilities').then((r) => r.data);

/** The ElevenLabs model new debates are voiced with (backend TTS_DEFAULT_MODEL_ID). */
export const ELEVENLABS_MODEL = 'eleven_v4';

/**
 * Voice catalogue for a provider. Pass a debate id for an existing debate, or the debate
 * language, the number of debaters and the show format (create wizard: a battle's host and
 * judge default to announcer voices) to get default voice assignments.
 */
export const getVoices = (
  provider: TTSProviderName,
  target: { debateId: string } | { language: string; participants: number; format?: string },
  ttsKey?: string,
) =>
  api
    .get<VoicesResponse>('/media/voices', {
      params:
        'debateId' in target
          ? { provider, debate_id: target.debateId }
          : { provider, language: target.language, participants: target.participants, format: target.format },
      headers: ttsKey ? { 'X-TTS-Key': ttsKey } : undefined,
      timeout: 60_000,
    })
    .then((r) => r.data);

export const getDebateMedia = (debateId: string) =>
  api.get<DebateMedia>(`/debates/${debateId}/media`).then((r) => r.data);

export const generateMedia = (debateId: string, body: GenerateMediaRequest) =>
  api
    .post<{ debate_id: string; media_status: string; message: string }>(`/debates/${debateId}/media`, body)
    .then((r) => r.data);

export const deleteMedia = (debateId: string) => api.delete(`/debates/${debateId}/media`).then(() => undefined);

/** timeline.json lives under /api/media/files, i.e. outside the axios baseURL. */
export const fetchTimeline = (url: string) => api.get<Timeline>(url, { baseURL: '' }).then((r) => r.data);

/** Absolute folder URL for Remotion, which needs full URLs for audio. Browser-only: the players
 *  and the renderer call it, pages pass the folder as the API gives it (a path). */
export const absoluteMediaBase = (base: string) => (base.startsWith('/') ? `${window.location.origin}${base}` : base);

/** The debate's media folder even before an audio build: pictures of the live scenes live there. */
export const debateFilesBase = (debateId: string) => `/api/media/files/${debateId}`;
