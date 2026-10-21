import { useEffect, useState } from 'react';
import { useDelayRender } from 'remotion';
import { readManifest, type SfxManifest } from './sfx';

/** public/sfx/manifest.json, fetched once; no folder or a broken file = no sounds. */
let loaded: SfxManifest | null = null;
let pending: Promise<SfxManifest> | null = null;

export const loadSfxManifest = (): Promise<SfxManifest> => {
  pending ??= fetch('/sfx/manifest.json')
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null)
    .then((raw: unknown) => (loaded = readManifest(raw)));
  return pending;
};

/** The manifest; holds the frame (delayRender) while it loads, so an MP4 starts with its sounds. */
export const useSfxManifest = (): SfxManifest | null => {
  const [manifest, setManifest] = useState<SfxManifest | null>(loaded);
  const { delayRender, continueRender } = useDelayRender();
  useEffect(() => {
    if (manifest) return;
    const handle = delayRender('Loading the crowd sounds');
    let cancelled = false;
    void loadSfxManifest().then((m) => {
      if (!cancelled) setManifest(m);
      continueRender(handle);
    });
    return () => {
      cancelled = true;
      continueRender(handle);
    };
  }, [manifest, delayRender, continueRender]);
  return manifest;
};
