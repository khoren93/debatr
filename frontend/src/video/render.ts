import { canRenderMediaOnWeb, renderMediaOnWeb, type CanRenderMediaOnWebResult, type RenderMediaOnWebProgress } from '@remotion/web-renderer';
import type { ComponentType } from 'react';
import { FPS } from './constants';

export interface RenderJob<P extends Record<string, unknown>> {
  id: string;
  component: ComponentType<P>;
  inputProps: P;
  width: number;
  height: number;
  durationInFrames: number;
  muted: boolean;
  scale: number; // 1 = full resolution, SCALE_720P = 720p from 1080p
  onProgress: (p: RenderMediaOnWebProgress) => void;
  signal: AbortSignal;
}

/** Exactly 2/3: the renderer rounds the scaled size up, and H.264 needs even sides
 * (0.6667 gave 1281×721 and the encoder refused it). */
export const SCALE_720P = 2 / 3;

export const checkRenderSupport = (width: number, height: number, muted: boolean): Promise<CanRenderMediaOnWebResult> =>
  canRenderMediaOnWeb({ container: 'mp4', videoCodec: 'h264', audioCodec: 'aac', width, height, muted });

/** Safari, and every browser on iOS, runs WebKit (its `navigator.vendor` is Apple's). */
const isWebKit = () => typeof navigator !== 'undefined' && /apple/i.test(navigator.vendor);

let realtimeEncoder = false;

/**
 * WebKit's H.264 encoder holds frames back in `latencyMode: 'quality'`, which the renderer
 * hard-codes, while the renderer waits for encoded frames before it draws more: in Safari the
 * export froze after the first frame. `realtime` hands each frame out at once (checked in
 * Playwright's WebKit: 300 frames with audio in 11 s). Installed once, so parallel renders are fine.
 */
const switchWebKitEncoderToRealtime = () => {
  const Native = globalThis.VideoEncoder;
  if (realtimeEncoder || !Native || !isWebKit()) return;
  class RealtimeEncoder extends Native {
    configure(config: VideoEncoderConfig) {
      super.configure({ ...config, latencyMode: 'realtime' });
    }
  }
  globalThis.VideoEncoder = RealtimeEncoder;
  realtimeEncoder = true;
};

/** Encode the composition to an MP4 in the browser (WebCodecs). */
export const renderMp4 = async <P extends Record<string, unknown>>(job: RenderJob<P>): Promise<{ blob: Blob; ms: number }> => {
  switchWebKitEncoderToRealtime();
  const t0 = performance.now();
  const { getBlob } = await renderMediaOnWeb({
    composition: { id: job.id, component: job.component, width: job.width, height: job.height, fps: FPS, durationInFrames: job.durationInFrames, defaultProps: job.inputProps },
    inputProps: job.inputProps,
    container: 'mp4',
    videoCodec: 'h264',
    audioCodec: 'aac',
    videoBitrate: 'high',
    audioBitrate: 'high',
    muted: job.muted,
    scale: job.scale,
    onProgress: job.onProgress,
    signal: job.signal,
    delayRenderTimeoutInMilliseconds: 60_000,
    logLevel: 'warn',
    licenseKey: 'free-license',
  });
  const blob = await getBlob();
  return { blob, ms: performance.now() - t0 };
};
