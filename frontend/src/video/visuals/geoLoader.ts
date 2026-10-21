import { useEffect, useState } from 'react';
import { useDelayRender } from 'remotion';
import type { Timeline } from '../../api/timeline';
import { DISPLAY_FONT, FONT, MONO_FONT } from '../constants';
import { preloadLogos } from '../logos';
import { loadSfxManifest } from '../sfxLoader';
import type { World } from './geo';

/** The world map is a lazy chunk + a JSON asset, loaded only for debates with a map scene. */
type GeoModule = typeof import('./geo');

export interface LoadedGeo {
  geo: GeoModule;
  world: World;
}

let loaded: LoadedGeo | null = null;
let pending: Promise<LoadedGeo> | null = null;

export const loadGeo = (): Promise<LoadedGeo> => {
  pending ??= import('./geo')
    .then(async (geo) => (loaded = { geo, world: await geo.loadWorld() }))
    .catch((err: unknown) => {
      pending = null;
      throw err;
    });
  return pending;
};

export const hasMapScene = (timeline: Timeline) => Boolean(timeline.visuals?.some((v) => v.scene.type === 'map'));

/** The web renderer draws text with whatever fonts are loaded at that moment: load the faces the
 *  frames use (the intro's headline, the mono labels, the captions). A missing font only falls
 *  back, so failures are ignored. */
const preloadFonts = () =>
  Promise.all([`800 100px ${DISPLAY_FONT}`, `500 30px ${MONO_FONT}`, `700 30px ${FONT}`, `400 30px ${FONT}`].map((font) => document.fonts.load(font))).catch(() => undefined);

/** Load what the frames of this timeline need before rendering them (MP4 export). */
export const preloadSceneAssets = async (timeline: Timeline): Promise<void> => {
  await Promise.all([hasMapScene(timeline) ? loadGeo() : null, preloadLogos(timeline), preloadFonts(), loadSfxManifest()]);
};

/** The loaded map; holds the frame (delayRender) while it is still loading. */
export const useGeo = (): LoadedGeo | null => {
  const [geo, setGeo] = useState<LoadedGeo | null>(loaded);
  const { delayRender, continueRender } = useDelayRender();
  useEffect(() => {
    if (geo) return;
    const handle = delayRender('Loading the world map');
    let cancelled = false;
    loadGeo().then(
      (g) => {
        if (!cancelled) setGeo(g);
        continueRender(handle);
      },
      () => continueRender(handle), // the scene renders without the map
    );
    return () => {
      cancelled = true;
      continueRender(handle);
    };
  }, [geo, delayRender, continueRender]);
  return geo;
};
