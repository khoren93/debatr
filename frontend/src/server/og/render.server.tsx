import { createHash } from 'node:crypto';
import { LRUCache } from 'lru-cache';
import { fromJsx } from 'takumi-js/helpers/jsx';
import { Renderer } from 'takumi-js/node';
import { OG_DESIGN, OG_HEIGHT, OG_WIDTH, SITE_CARD, ogVersion, type OgCard } from '../../lib/og';
import { readImage, writeImage, type StoredImage } from './cache.server';
import { OgCardView, cardLogos } from './card.server';
import { ensureScriptFonts, registerBundledFonts, scriptFamilies } from './fonts.server';

/**
 * Draws preview cards with Takumi (Rust, no browser: ~20–40 ms a card) and serves them from
 * memory (64 cards) or disk (cache.server) when the same card was drawn before. A card is keyed
 * by its data and OG_DESIGN, so two debates with the same question and lineup share one file and a
 * change of either draws a new one.
 */

/** Past it the card is sent as JPEG (social networks take both; gradients make PNGs heavy). */
const PNG_MAX_BYTES = 300 * 1024;
const JPEG_QUALITY = 90;

export interface OgImage extends StoredImage {
  /** False when fonts for its script could not be fetched: drawn with gaps, not kept. */
  complete: boolean;
}

const renderer = new Renderer({ cacheMaxBytes: 16 * 1024 * 1024 });
let fontsReady: Promise<void> | null = null;
const ready = () => {
  fontsReady ??= registerBundledFonts(renderer).catch((err: unknown) => {
    fontsReady = null;
    throw err;
  });
  return fontsReady;
};

const memory = new LRUCache<string, OgImage>({ max: 64, maxSize: 24 * 1024 * 1024, sizeCalculation: (image) => Math.max(1, image.body.byteLength) });
const drawing = new Map<string, Promise<OgImage>>();

export const cardKey = (card: OgCard) => createHash('sha256').update(JSON.stringify([OG_DESIGN, card])).digest('hex').slice(0, 32);

async function draw(card: OgCard): Promise<OgImage> {
  await ready();
  const scripts = scriptFamilies(card.text, card.lang);
  const complete = await ensureScriptFonts(renderer, scripts, card.text);
  const { node, css } = await fromJsx(<OgCardView card={card} scripts={scripts} />);
  const options = { width: OG_WIDTH, height: OG_HEIGHT, css, images: cardLogos(card), lang: card.lang };
  const png = await renderer.render(node, { ...options, format: 'png' });
  if (png.byteLength <= PNG_MAX_BYTES) return { body: png, type: 'image/png', complete };
  return { body: await renderer.render(node, { ...options, format: 'jpeg', quality: JPEG_QUALITY }), type: 'image/jpeg', complete };
}

/** The card's picture: from memory, from disk, or drawn now (once, however many ask at a time). */
export function ogImage(card: OgCard): Promise<OgImage> {
  const key = cardKey(card);
  const hit = memory.get(key);
  if (hit) return Promise.resolve(hit);
  let job = drawing.get(key);
  if (!job) {
    job = (async () => {
      const stored = await readImage(key);
      if (stored) {
        const image = { ...stored, complete: true };
        memory.set(key, image);
        return image;
      }
      const image = await draw(card);
      if (image.complete) {
        memory.set(key, image);
        await writeImage(key, image);
      }
      return image;
    })().finally(() => drawing.delete(key));
    drawing.set(key, job);
  }
  return job;
}

/** A picture whose URL names its version (`?v=` = ogVersion) never changes: cached for good;
 *  without it (sitemaps, oEmbed) or with an old one, for an hour; drawn with gaps, briefly. */
export const imageResponse = (image: OgImage, request: Request, card: OgCard): Response => {
  const exact = new URL(request.url).searchParams.get('v') === ogVersion(card);
  const cache = !image.complete ? 'public, max-age=300' : exact ? 'public, max-age=31536000, immutable' : 'public, max-age=3600';
  return new Response(request.method === 'HEAD' ? null : (image.body as Uint8Array<ArrayBuffer>), {
    headers: { 'Content-Type': image.type, 'Content-Length': String(image.body.byteLength), 'Cache-Control': cache },
  });
};

/** Status of what `serverApi` threw: route error data (`data(…, {status})`) or a Response. */
const thrownStatus = (err: unknown): number | null => {
  if (err instanceof Response) return err.status;
  if (err && typeof err === 'object' && 'init' in err) {
    const init = (err as { init?: { status?: number } | null }).init;
    return typeof init?.status === 'number' ? init.status : null;
  }
  return null;
};

/**
 * The image route of a page: its card from `load` (the API's public copy), drawn. A page that is
 * not public answers its status without a picture; an API that does not answer gets the site's
 * card for a minute, so a preview still shows something.
 */
export async function ogRoute(request: Request, load: () => Promise<OgCard>): Promise<Response> {
  let card: OgCard;
  try {
    card = await load();
  } catch (err) {
    if (request.signal.aborted) throw err;
    const status = thrownStatus(err);
    if (status && status >= 400 && status < 500) {
      return new Response(null, { status: status === 410 ? 410 : 404, headers: { 'Cache-Control': 'public, max-age=300' } });
    }
    const fallback = await ogImage(SITE_CARD);
    const response = imageResponse(fallback, request, SITE_CARD);
    response.headers.set('Cache-Control', 'public, max-age=60');
    return response;
  }
  return imageResponse(await ogImage(card), request, card);
}
