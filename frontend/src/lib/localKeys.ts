import { useSyncExternalStore } from 'react';

/**
 * Personal provider keys kept only in this browser (localStorage). They are sent with the
 * single request that needs them; the server parks them in Redis with a TTL for the running
 * job and never writes them to Postgres. The OpenRouter key can additionally be stored on the
 * account (encrypted) — that is a separate, explicit feature (`KeyCard`).
 */
export type LocalKeyName = 'openrouter' | 'elevenlabs';

const STORAGE_KEYS: Record<LocalKeyName, string> = {
  openrouter: 'debatr.openrouter_key',
  elevenlabs: 'debatr.elevenlabs_key',
};

const listeners = new Set<() => void>();

export const getLocalKey = (name: LocalKeyName): string => {
  try {
    return localStorage.getItem(STORAGE_KEYS[name]) ?? '';
  } catch {
    return '';
  }
};

/** Save (or remove, when blank) a key and notify every `useLocalKey` subscriber. */
export const setLocalKey = (name: LocalKeyName, value: string) => {
  try {
    const key = value.trim();
    if (key) localStorage.setItem(STORAGE_KEYS[name], key);
    else localStorage.removeItem(STORAGE_KEYS[name]);
  } catch {
    /* storage unavailable */
  }
  listeners.forEach((notify) => notify());
};

const subscribe = (notify: () => void) => {
  listeners.add(notify);
  // Other tabs: keep the wizard / dialogs in sync with the Account page.
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || Object.values(STORAGE_KEYS).includes(e.key)) notify();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(notify);
    window.removeEventListener('storage', onStorage);
  };
};

/** The stored key ('' when none); re-renders when it changes in this or another tab. */
export const useLocalKey = (name: LocalKeyName): string =>
  useSyncExternalStore(subscribe, () => getLocalKey(name), () => '');

/** "sk-or…abcd" — enough to recognise a key without revealing it. */
export const maskKey = (key: string) => (key.length > 12 ? `${key.slice(0, 5)}…${key.slice(-4)}` : '…' + key.slice(-2));
