import { Audio } from '@remotion/media';
import { Sequence, useVideoConfig } from 'remotion';
import type { Timeline } from '../../api/timeline';
import { SFX_MAX_MS, sfxCues, sfxOn } from '../sfx';
import { useSfxManifest } from '../sfxLoader';
import { msToFrame } from '../timing';

/** The crowd / studio sounds of the show (video/sfx.ts) between `fromMs` and `toMs` on its
 *  track; `offsetMs` = where the track's 0 sits on the composition's clock. Files from public/sfx,
 *  same origin as the page (the player, the MP4 render and the embed), only those its manifest
 *  lists. */
export const SfxTrack = ({ timeline, offsetMs, fromMs = -Infinity, toMs = Infinity }: { timeline: Timeline; offsetMs: number; fromMs?: number; toMs?: number }) =>
  sfxOn(timeline) ? <Cues timeline={timeline} offsetMs={offsetMs} fromMs={fromMs} toMs={toMs} /> : null;

const Cues = ({ timeline, offsetMs, fromMs, toMs }: { timeline: Timeline; offsetMs: number; fromMs: number; toMs: number }) => {
  const { fps } = useVideoConfig();
  const manifest = useSfxManifest();
  if (!manifest) return null;
  return (
    <>
      {sfxCues(timeline, manifest)
        .filter((cue) => cue.atMs >= fromMs && cue.atMs < toMs)
        .map((cue) => (
          <Sequence key={`${cue.file}@${cue.atMs}`} from={msToFrame(cue.atMs + offsetMs, fps)} durationInFrames={msToFrame(SFX_MAX_MS, fps)} premountFor={fps}>
            <Audio src={`/sfx/${cue.file}`} volume={cue.volume} />
          </Sequence>
        ))}
    </>
  );
};
