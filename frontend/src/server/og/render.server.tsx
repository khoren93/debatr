import { createHash } from 'node:crypto';
import { LRUCache } from 'lru-cache';
import { fromJsx } from 'takumi-js/helpers/jsx';
import { Renderer } from 'takumi-js/node';
import { OG_DESIGN, OG_HEIGHT, OG_WIDTH, SITE_CARD, ogVersion, type OgCard } from '../../lib/og';
import { apiInternalUrl } from '../../api/server.server';
import { readImage, writeImage, type StoredImage } from './cache.server';
import { OgCardView, cardLogos } from './card.server';
import { ensureScriptFonts, registerBundledFonts, scriptFamilies } from './fonts.server';
import { logoName, logoSource } from './logos.server';

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

/** An AI cover's 1200×630 file from the API (cached like a card); null when it is gone. */
async function coverImage(cover: { id: string; url: string }): Promise<OgImage | null> {
  const key = `cover-${cover.id.replace(/[^a-z0-9]/gi, '')}`;
  const hit = memory.get(key);
  if (hit) return hit;
  try {
    const response = await fetch(`${apiInternalUrl()}${cover.url}`, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) return null;
    const image: OgImage = { body: new Uint8Array(await response.arrayBuffer()), type: 'image/jpeg', complete: true };
    memory.set(key, image);
    return image;
  } catch {
    return null;
  }
}

/** The card's picture: its AI cover, or from memory, from disk, or drawn now (once, however
 *  many ask at a time). */
export async function ogImage(card: OgCard): Promise<OgImage> {
  if (card.cover) {
    const cover = await coverImage(card.cover);
    if (cover) return cover;
    const drawn = await ogImage({ ...card, cover: null });
    return { ...drawn, complete: false }; // the cover will be back: ask again soon
  }
  return drawCard(card);
}

function drawCard(card: OgCard): Promise<OgImage> {
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

// --- logo references of the AI covers -----------------------------------------------------------

const LOGO_SIZE = 512;
const LOGO_PAD = 40;
/** Logos drawn in white (made for dark backgrounds) go on a near-black tile. */
const DARK_TILES = new Set(['kimi-color']);
const logos = new LRUCache<string, { name: string; body: Uint8Array }>({ max: 64 });

/**
 * A model's logo as the image model's reference picture (backend services/media/cover_logos):
 * 512 px PNG on white, single-colour logos in near-black. Null for authors without a logo.
 */
export async function logoReference(modelId: string): Promise<{ name: string; body: Uint8Array } | null> {
  const logo = logoSource(modelId, '#111111');
  if (!logo) return null;
  const name = logoName(logo.src);
  const hit = logos.get(name);
  if (hit) return hit;
  const { node, css } = await fromJsx(
    <div style={{ display: 'flex', width: LOGO_SIZE, height: LOGO_SIZE, alignItems: 'center', justifyContent: 'center', background: DARK_TILES.has(name) ? '#0A0B0F' : '#FFFFFF' }}>
      <img src={logo.src} style={{ width: LOGO_SIZE - 2 * LOGO_PAD, height: LOGO_SIZE - 2 * LOGO_PAD }} />
    </div>,
  );
  const body = await renderer.render(node, { width: LOGO_SIZE, height: LOGO_SIZE, format: 'png', css, images: [logo] });
  const entry = { name, body };
  logos.set(name, entry);
  return entry;
}
