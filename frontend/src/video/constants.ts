export const FPS = 30;
export const LONG_W = 1920;
export const LONG_H = 1080;
export const SHORT_W = 1080;
export const SHORT_H = 1920;
export const INTRO_MS = 1800;
export const OUTRO_MS = 2200;
export const SHORT_HOOK_MS = 1600;
export const SHORT_END_MS = 1400;
/** Size of the scene stage in the 16:9 video; posters and replays use the same box. */
export const POSTER_W = 1160;
export const POSTER_H = 700;
// The page's own faces (src/fonts.ts): the player and the MP4 export draw with them.
export const FONT = "'DM Sans Variable', 'DM Sans', Inter, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
export const DISPLAY_FONT = "'Bricolage Grotesque Variable', 'Bricolage Grotesque', 'DM Sans Variable', Inter, -apple-system, 'Segoe UI', Roboto, sans-serif";
export const MONO_FONT = "'JetBrains Mono Variable', 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace";
export const ACCENT = '#D9FF3D';

/** Display size that keeps a headline within about three lines (the video's intro and hook, the page's poster). */
export const headlineSize = (text: string, base: number) => (text.length <= 60 ? base : text.length <= 100 ? base * 0.84 : base * 0.7);

/** Height of the video's top bar: the speaking chip's (3u logo + padding + border); brand and round match it. */
export const barHeight = (u: number) => 4.2 * u + 4;
