import { modelIcon } from '../../lib/modelIcons';

/**
 * Provider logos for the preview cards: the site's own SVGs (public/model-icons, read into the
 * server bundle at build time), handed to Takumi as image sources. Single-colour logos are drawn
 * white, as on the gallery cover (where they are a white mask).
 */

const FILES = import.meta.glob<string>('../../../public/model-icons/*.svg', { query: '?raw', import: 'default', eager: true });

const SVG = new Map(Object.entries(FILES).map(([path, svg]) => [`/model-icons/${path.split('/').pop()}`, svg]));

export interface LogoSource {
  /** The `<img src>` the card uses and Takumi's key for the bytes. */
  src: string;
  data: Uint8Array;
}

const encoder = new TextEncoder();

/** The logo of `modelId` as an image source (single-colour logos in `mono`), or null for
 *  authors without one (letter tile). */
export const logoSource = (modelId: string, mono = '#FFFFFF'): LogoSource | null => {
  const icon = modelIcon(modelId);
  const svg = icon && SVG.get(icon.src);
  if (!icon || !svg) return null;
  return { src: `logo:${icon.src}`, data: encoder.encode(icon.mono ? svg.replace(/currentColor/g, mono) : svg) };
};

/** The logo's file name without extension ("claude-color"): its name for the AI covers. */
export const logoName = (src: string) => src.split('/').pop()?.replace(/\.svg$/, '') ?? '';
