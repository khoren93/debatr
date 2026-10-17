import { useEffect, useState } from 'react';
import { useDelayRender } from 'remotion';
import type { Timeline } from '../api/timeline';
import { modelIcon } from '../lib/modelIcons';
import { speakerModelId } from './speakers';

/** Single-colour provider logos are SVGs drawn in `currentColor`. The MP4 web renderer takes only
 *  raster mask images, so they are painted once onto a canvas in the wanted colour (PNG data URL). */
const SIZE = 256;
export const LOGO_COLOR = '#F2F3F7';
const ready = new Map<string, string>();
const pending = new Map<string, Promise<string>>();

const keyOf = (src: string, color: string) => `${src}|${color}`;

export const tintLogo = (src: string, color: string): Promise<string> => {
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
        ctx.globalCompositeOperation = 'source-in';
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, SIZE, SIZE);
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

/** The tinted logo; holds the frame (delayRender) until it is painted. */
export const useTintedLogo = (src: string | null, color: string): string | null => {
  const key = src ? keyOf(src, color) : '';
  // The same component may show another speaker's logo later (the speaking chip).
  const [painted, setPainted] = useState<{ key: string; url: string } | null>(null);
  const url = src ? (painted?.key === key ? painted.url : (ready.get(key) ?? null)) : null;
  const { delayRender, continueRender } = useDelayRender();
  const has = url !== null;
  useEffect(() => {
    if (!src || has) return;
    const handle = delayRender(`Painting the logo ${src}`);
    let cancelled = false;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      continueRender(handle);
    };
    tintLogo(src, color).then(
      (u) => {
        if (!cancelled) setPainted({ key: keyOf(src, color), url: u });
        release();
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

/** Paint every speaker's single-colour logo before an export starts. */
export const preloadLogos = async (timeline: Timeline, color = LOGO_COLOR): Promise<void> => {
  const srcs = new Set<string>();
  for (const s of timeline.speakers) {
    const icon = modelIcon(speakerModelId(s));
    if (icon?.mono) srcs.add(icon.src);
  }
  await Promise.all([...srcs].map((src) => tintLogo(src, color).catch(() => undefined)));
};
