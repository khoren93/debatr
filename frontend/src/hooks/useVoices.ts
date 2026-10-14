import { useEffect, useState } from 'react';
import { getErrorMessage } from '../api/client';
import { getVoices } from '../api/media';
import type { TTSProviderName, VoiceInfo } from '../api/types';

interface Loaded {
  key: string;
  voices: VoiceInfo[];
  defaults: Record<string, string>;
}

interface Failed {
  key: string;
  message: string;
}

export interface VoiceCatalogue {
  voices: VoiceInfo[];
  /** Default voice per speaker id: `participant_0` = moderator, `participant_1..n` = debaters, `judge`. */
  defaults: Record<string, string>;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Voice catalogue + default assignments for the create wizard. Re-fetches whenever the
 * provider, the debate language, the number of debaters or the user's ElevenLabs key changes.
 * Results are tagged with their request key so stale data from a previous provider is never
 * returned.
 */
export const useVoices = (provider: TTSProviderName, language: string, debaters: number, enabled = true, ttsKey = ''): VoiceCatalogue => {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState<Failed | null>(null);
  const [attempt, setAttempt] = useState(0);

  const key = `${provider}|${language.trim().toLowerCase()}|${debaters}|${ttsKey.slice(-6)}|${attempt}`;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    getVoices(provider, { language, participants: debaters }, ttsKey || undefined)
      .then((res) => {
        if (!cancelled) setLoaded({ key, voices: res.voices, defaults: res.defaults });
      })
      .catch((err: unknown) => {
        if (!cancelled) setFailed({ key, message: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, key, provider, language, debaters, ttsKey]);

  const current = loaded?.key === key ? loaded : null;
  const error = failed?.key === key ? failed.message : null;

  return {
    voices: current?.voices ?? [],
    defaults: current?.defaults ?? {},
    loading: enabled && !current && !error,
    error,
    reload: () => setAttempt((n) => n + 1),
  };
};
