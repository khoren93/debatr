import { createHash } from 'node:crypto';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { googleFonts, subsetFonts, type FetchLike } from 'takumi-js/helpers';
import type { Renderer } from 'takumi-js/node';
import { cacheDir } from './cache.server';

/**
 * Fonts of the preview cards. Takumi never reads system fonts, so every glyph comes from here:
 * the site's own families (the same woff2 files as `@fontsource-variable/*`) and Noto for the
 * other scripts the wizard offers (Cyrillic, Greek, Devanagari, Armenian, Arabic, Hebrew) are read
 * from node_modules once; emoji come from Twemoji's COLR font. Chinese, Japanese, Korean and a few
 * more scripts would weigh hundreds of megabytes, so their Noto subsets are fetched from Google
 * Fonts when a headline needs them (only the subsets it uses, kept on disk afterwards).
 */

export const DISPLAY = 'Bricolage Grotesque';
export const MONO = 'JetBrains Mono';
const EMOJI = 'Twemoji';

interface Bundled {
  family: string;
  /** Package and file name pattern (`{subset}`) under its `files/`. */
  pkg: string;
  file: string;
  subsets: string[];
  generic?: 'emoji';
}

/** Weight 800 is the headline's; the static Noto families are only needed there. */
const BUNDLED: Bundled[] = [
  { family: DISPLAY, pkg: '@fontsource-variable/bricolage-grotesque', file: 'bricolage-grotesque-{subset}-wght-normal.woff2', subsets: ['latin', 'latin-ext', 'vietnamese'] },
  { family: MONO, pkg: '@fontsource-variable/jetbrains-mono', file: 'jetbrains-mono-{subset}-wght-normal.woff2', subsets: ['latin', 'latin-ext', 'cyrillic', 'cyrillic-ext', 'greek', 'vietnamese'] },
  {
    family: 'Noto Sans',
    pkg: '@fontsource-variable/noto-sans',
    file: 'noto-sans-{subset}-wght-normal.woff2',
    subsets: ['latin', 'latin-ext', 'cyrillic', 'cyrillic-ext', 'greek', 'greek-ext', 'vietnamese', 'devanagari'],
  },
  { family: 'Noto Sans Armenian', pkg: '@fontsource/noto-sans-armenian', file: 'noto-sans-armenian-{subset}-800-normal.woff2', subsets: ['armenian'] },
  { family: 'Noto Sans Arabic', pkg: '@fontsource/noto-sans-arabic', file: 'noto-sans-arabic-{subset}-800-normal.woff2', subsets: ['arabic'] },
  { family: 'Noto Sans Hebrew', pkg: '@fontsource/noto-sans-hebrew', file: 'noto-sans-hebrew-{subset}-800-normal.woff2', subsets: ['hebrew'] },
];

/** Fallback order after the card's own family: every bundled script, then emoji. */
const FALLBACKS = ['Noto Sans', 'Noto Sans Armenian', 'Noto Sans Arabic', 'Noto Sans Hebrew'];

/** `font-family` of a text in `family`, falling back through the bundled scripts, the families
 *  fetched for this headline (`extra`) and emoji. */
export const fontStack = (family: string, extra: string[] = []) => [family, ...FALLBACKS, ...extra, EMOJI].map((f) => `"${f}"`).join(', ');

/** "U+0460-052F,U+1C80" (fontsource's unicode.json) → inclusive codepoint ranges. */
export const parseUnicodeRange = (text: string): [number, number][] =>
  text
    .split(',')
    .map((part) => part.trim().replace(/^U\+/i, ''))
    .filter(Boolean)
    .map((part) => {
      const [from, to = from] = part.split('-');
      return [parseInt(from, 16), parseInt(to, 16)] as [number, number];
    })
    .filter(([from, to]) => Number.isFinite(from) && Number.isFinite(to));

const require = createRequire(import.meta.url);

/** Registers the bundled families (once per process). */
export async function registerBundledFonts(renderer: Renderer): Promise<void> {
  const jobs: Promise<unknown>[] = [];
  for (const font of BUNDLED) {
    const ranges = JSON.parse(await readFile(require.resolve(`${font.pkg}/unicode.json`), 'utf8')) as Record<string, string>;
    for (const subset of font.subsets) {
      const path = require.resolve(`${font.pkg}/files/${font.file.replace('{subset}', subset)}`);
      jobs.push(readFile(path).then((data) => renderer.registerFont({ name: font.family, data, unicodeRange: parseUnicodeRange(ranges[subset] ?? '') })));
    }
  }
  jobs.push(readFile(require.resolve('twemoji-colr-font/twemoji.woff2')).then((data) => renderer.registerFont({ name: EMOJI, data, generic: 'emoji' })));
  await Promise.all(jobs);
}

// --- scripts fetched on demand ------------------------------------------------------------------

const ON_DEMAND: { test: RegExp; family: (lang: string) => string }[] = [
  { test: /[぀-ヿㇰ-ㇿｦ-ﾟ]/u, family: () => 'Noto Sans JP' },
  { test: /[ᄀ-ᇿ㄰-㆏ꥠ-꥿가-힯]/u, family: () => 'Noto Sans KR' },
  {
    test: /\p{Script=Han}/u,
    family: (lang) => (/^ja/i.test(lang) ? 'Noto Sans JP' : /^ko/i.test(lang) ? 'Noto Sans KR' : /^zh-(tw|hk|mo|hant)/i.test(lang) ? 'Noto Sans TC' : 'Noto Sans SC'),
  },
  { test: /\p{Script=Thai}/u, family: () => 'Noto Sans Thai' },
  { test: /\p{Script=Georgian}/u, family: () => 'Noto Sans Georgian' },
  { test: /\p{Script=Bengali}/u, family: () => 'Noto Sans Bengali' },
  { test: /\p{Script=Tamil}/u, family: () => 'Noto Sans Tamil' },
  { test: /\p{Script=Telugu}/u, family: () => 'Noto Sans Telugu' },
  { test: /\p{Script=Gujarati}/u, family: () => 'Noto Sans Gujarati' },
  { test: /\p{Script=Gurmukhi}/u, family: () => 'Noto Sans Gurmukhi' },
  { test: /\p{Script=Kannada}/u, family: () => 'Noto Sans Kannada' },
  { test: /\p{Script=Malayalam}/u, family: () => 'Noto Sans Malayalam' },
  { test: /\p{Script=Sinhala}/u, family: () => 'Noto Sans Sinhala' },
  { test: /\p{Script=Khmer}/u, family: () => 'Noto Sans Khmer' },
  { test: /\p{Script=Lao}/u, family: () => 'Noto Sans Lao' },
  { test: /\p{Script=Myanmar}/u, family: () => 'Noto Sans Myanmar' },
  { test: /\p{Script=Ethiopic}/u, family: () => 'Noto Sans Ethiopic' },
];

/** Families to fetch for `text` (in `lang`), beyond the bundled ones. */
export const scriptFamilies = (text: string, lang: string): string[] => [...new Set(ON_DEMAND.filter((s) => s.test.test(text)).map((s) => s.family(lang)))];

/** Google's css2 answers change rarely (their font URLs are versioned): re-asked after a week. */
const CSS_MAX_AGE_MS = 7 * 24 * 3600_000;
const FETCH_TIMEOUT_MS = 4000;
/** Fetched subsets kept registered at most; past it they are dropped and fetched (from disk) again. */
const ON_DEMAND_BUDGET = 32 * 1024 * 1024;

/** fetch with a disk copy of every good answer (the css2 sheets and the font files). */
const diskFetch: FetchLike = async (url, init) => {
  const dir = await cacheDir('fonts');
  const file = dir && join(dir, `${createHash('sha256').update(url).digest('hex').slice(0, 40)}.bin`);
  if (file) {
    try {
      const fresh = !url.includes('/css2?') || Date.now() - (await stat(file)).mtimeMs < CSS_MAX_AGE_MS;
      if (fresh) return new Response(new Uint8Array(await readFile(file)));
    } catch {
      // Not on disk yet.
    }
  }
  const response = await fetch(url, init);
  if (!response.ok || !file) return response;
  const body = new Uint8Array(await response.arrayBuffer());
  writeFile(file, body).catch(() => undefined);
  return new Response(body, { status: response.status, headers: response.headers });
};

/** Subsets registered (or being registered) on demand, by key; their families and bytes. */
const registered = new Map<string, Promise<void>>();
const onDemandFamilies = new Set<string>();
let registeredBytes = 0;

/**
 * Registers the subsets of `families` that `text` uses. False when some could not be fetched:
 * the picture is then drawn with gaps and must not be kept.
 */
export async function ensureScriptFonts(renderer: Renderer, families: string[], text: string): Promise<boolean> {
  if (!families.length) return true;
  try {
    const subsets = await googleFonts({ families: families.map((name) => ({ name, weight: 800 })), fetch: diskFetch, timeout: FETCH_TIMEOUT_MS });
    if (registeredBytes > ON_DEMAND_BUDGET) {
      for (const name of onDemandFamilies) renderer.unregisterFont({ name });
      onDemandFamilies.clear();
      registered.clear();
      registeredBytes = 0;
    }
    await Promise.all(
      subsetFonts({ fonts: subsets, source: text }).map((s) => {
        let job = registered.get(s.key);
        if (!job) {
          job = (async () => {
            const data = await s.data();
            await renderer.registerFont({ key: s.key, name: s.name, data, weight: s.weight, style: s.style, unicodeRange: s.unicodeRange });
            onDemandFamilies.add(s.name);
            registeredBytes += data.byteLength;
          })();
          job.catch(() => registered.delete(s.key));
          registered.set(s.key, job);
        }
        return job;
      }),
    );
    return true;
  } catch (err) {
    console.warn(`[og] fonts ${families.join(', ')}: ${err instanceof Error ? err.message : err}`);
    return false;
  }
}
