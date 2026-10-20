import { mkdir, readFile, readdir, stat, unlink, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/**
 * Disk cache of the preview cards (`images/`) and the fonts fetched for them (`fonts/`):
 * OG_CACHE_DIR (compose: the `og_cache` volume, so a deploy does not redraw every picture), else a
 * folder in the system's temp dir. Without a writable folder the cards are only kept in memory.
 * Images past OG_CACHE_MAX_MB are pruned, least recently used first.
 */

const ROOT = process.env.OG_CACHE_DIR || join(tmpdir(), 'debatr-og');
const MAX_BYTES = (Number(process.env.OG_CACHE_MAX_MB) || 256) * 1024 * 1024;
/** Pruning lists the folder: once per this many writes. */
const PRUNE_EVERY = 50;

const dirs = new Map<string, Promise<string | null>>();

/** The cache's `sub` folder, created on first use; null when the disk cannot be written. */
export const cacheDir = (sub: 'images' | 'fonts'): Promise<string | null> => {
  let dir = dirs.get(sub);
  if (!dir) {
    const path = join(ROOT, sub);
    dir = mkdir(path, { recursive: true }).then(
      () => path,
      (err: unknown) => {
        console.warn(`[og] no disk cache in ${path}: ${err instanceof Error ? err.message : err}`);
        return null;
      },
    );
    dirs.set(sub, dir);
  }
  return dir;
};

export interface StoredImage {
  body: Uint8Array;
  type: 'image/png' | 'image/jpeg';
}

const EXT = { 'image/png': 'png', 'image/jpeg': 'jpg' } as const;

export async function readImage(key: string): Promise<StoredImage | null> {
  const dir = await cacheDir('images');
  if (!dir) return null;
  for (const type of ['image/png', 'image/jpeg'] as const) {
    const file = join(dir, `${key}.${EXT[type]}`);
    try {
      const body = new Uint8Array(await readFile(file));
      const now = new Date();
      utimes(file, now, now).catch(() => undefined); // recently used: pruned last
      return { body, type };
    } catch {
      // Not this one.
    }
  }
  return null;
}

let writes = 0;

export async function writeImage(key: string, image: StoredImage): Promise<void> {
  const dir = await cacheDir('images');
  if (!dir) return;
  try {
    await writeFile(join(dir, `${key}.${EXT[image.type]}`), image.body);
    if (++writes % PRUNE_EVERY === 0) await prune(dir);
  } catch (err) {
    console.warn(`[og] cache write: ${err instanceof Error ? err.message : err}`);
  }
}

/** Oldest files out until the folder is under 80 % of MAX_BYTES. */
async function prune(dir: string): Promise<void> {
  const files = await Promise.all(
    (await readdir(dir)).map(async (name) => {
      const info = await stat(join(dir, name)).catch(() => null);
      return info ? { name, size: info.size, used: info.mtimeMs } : null;
    }),
  );
  const present = files.filter((f): f is NonNullable<typeof f> => !!f);
  let total = present.reduce((sum, f) => sum + f.size, 0);
  if (total <= MAX_BYTES) return;
  for (const file of present.sort((a, b) => a.used - b.used)) {
    if (total <= MAX_BYTES * 0.8) break;
    await unlink(join(dir, file.name)).catch(() => undefined);
    total -= file.size;
  }
}
