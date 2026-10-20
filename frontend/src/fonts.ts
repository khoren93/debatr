/**
 * The site's and the console's typefaces from our own origin (fontsource: the same variable files
 * Google Fonts serves, Bricolage Grotesque and DM Sans with the optical-size axis). Each subset
 * downloads only when a page uses its characters (unicode-range). The family names carry
 * "Variable" (index.css tokens, video/constants.ts); the video export loads the same faces.
 */
import '@fontsource-variable/bricolage-grotesque/opsz.css';
import '@fontsource-variable/dm-sans/opsz.css';
import '@fontsource-variable/jetbrains-mono/wght.css';
import displayLatin from '@fontsource-variable/bricolage-grotesque/files/bricolage-grotesque-latin-opsz-normal.woff2?url';
import sansLatin from '@fontsource-variable/dm-sans/files/dm-sans-latin-opsz-normal.woff2?url';

/** Faces every page shows above the fold (body text, headings): `<link rel="preload">`. */
export const PRELOAD_FONTS = [sansLatin, displayLatin];
