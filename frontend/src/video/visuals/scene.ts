/** What every scene component receives besides its data. */
export interface SceneCtx {
  id: string; // visual id, seeds the hand-drawn strokes and SVG ids
  t: number; // ms since the scene appeared
  dur: number; // scene length, ms
  items: number[]; // reveal time per element, ms relative to the scene start
  w: number; // body box, px
  h: number;
  k: number; // type scale: 1 = the 16:9 stage
  color: string; // speaker colour
  speaker: string; // speaker name
  locale: string; // debate language code, for number formatting
}

/** A colour that is not the speaker's, for second series / the other side. */
export const PALETTE = ['#FFC46B', '#6C9CFF', '#A78BFA', '#34D399', '#FF7A66', '#F472B6'];

export const seriesColors = (own: string, n: number): string[] => [own, ...PALETTE.filter((c) => c.toLowerCase() !== own.toLowerCase())].slice(0, n);
