import { useEffect, useState } from 'react';
import { useDelayRender } from 'remotion';
import type { Timeline } from '../api/timeline';
import { modelIcon } from '../lib/modelIcons';
import { speakerModelId } from './speakers';

/** Provider logos are SVGs. The MP4 web renderer takes only raster mask images, and WebKit draws an
 *  SVG sized in em (LobeHub's `width="1em"`) zoomed and cropped onto its canvas, so every logo is
 *  painted once onto a canvas as a PNG data URL: single-colour ones in the wanted colour
 *  (`color`), colour ones as they are (`color = null`). */
const SIZE = 256;
export const LOGO_COLOR = '#F2F3F7';
const ready = new Map<string, string>();
const pending = new Map<string, Promise<string>>();

const keyOf = (src: string, color: string | null) => `${src}|${color ?? 'original'}`;

export const paintLogo = (src: string, color: string | null): Promise<string> => {
  const key = keyOf(src, color);
  const done = ready.get(key);
  if (done) return Promise.resolve(done);
  let job = pending.get(key);
  if (!job) {
    job = new Promise<string>((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = SIZE;
        canvas.height = SIZE;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          reject(new Error('Canvas is not available'));
          return;
        }
        ctx.drawImage(img, 0, 0, SIZE, SIZE);
        if (color) {
          ctx.globalCompositeOperation = 'source-in';
          ctx.fillStyle = color;
          ctx.fillRect(0, 0, SIZE, SIZE);
        }
        const url = canvas.toDataURL('image/png');
        ready.set(key, url);
        resolve(url);
      };
      img.onerror = () => reject(new Error(`Could not load the logo ${src}`));
      img.src = src;
    }).finally(() => pending.delete(key));
    pending.set(key, job);
  }
  return job;
};

/** The painted logo; holds the frame (delayRender) until it is ready. */
export const usePaintedLogo = (src: string | null, color: string | null): string | null => {
  const key = src ? keyOf(src, color) : '';
  // The same component may show another speaker's logo later (the speaking chip).
  const [painted, setPainted] = useState<{ key: string; url: string } | null>(null);
  const url = src ? (painted?.key === key ? painted.url : (ready.get(key) ?? null)) : null;
  const { delayRender, continueRender } = useDelayRender();
  const has = url !== null;
  useEffect(() => {
    if (!src || has) return;
    // Held until the painted logo is on screen: this cleanup runs after the re-render that shows
    // it (`has` flips), so the renderer never captures the empty tile in between.
    const handle = delayRender(`Painting the logo ${src}`);
    let cancelled = false;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      continueRender(handle);
    };
    paintLogo(src, color).then(
      (u) => {
        if (cancelled) release();
        else setPainted({ key: keyOf(src, color), url: u });
      },
      release, // the tile stays empty rather than failing the render
    );
    return () => {
      cancelled = true;
      release();
    };
  }, [src, color, has, delayRender, continueRender]);
  return url;
};

/** Paint every speaker's logo before an export starts. */
export const preloadLogos = async (timeline: Timeline, color = LOGO_COLOR): Promise<void> => {
  const jobs = new Map<string, Promise<unknown>>();
  for (const s of timeline.speakers) {
    const icon = modelIcon(speakerModelId(s));
    if (icon && !jobs.has(icon.src)) jobs.set(icon.src, paintLogo(icon.src, icon.mono ? color : null).catch(() => undefined));
  }
  await Promise.all(jobs.values());
};
