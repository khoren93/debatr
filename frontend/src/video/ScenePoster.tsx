import { AbsoluteFill, useCurrentFrame, useVideoConfig } from 'remotion';
import type { TimelineVisual } from '../api/visuals';
import { frameToMs } from './utils';
import { ScenePanel, type SceneCast } from './visuals/SceneStage';

/** Size of the scene stage in the 16:9 video; posters and replays use the same box. */
export const POSTER_W = 1160;
export const POSTER_H = 700;

export interface ScenePosterProps {
  visual: TimelineVisual; // start_ms = 0: times are relative to the scene
  cast: SceneCast;
  mediaBase: string;
  [key: string]: unknown;
}

/** One visual scene on its own (transcript board): a still of the final state or a replay. */
export const ScenePoster = ({ visual, cast, mediaBase }: ScenePosterProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = Math.min(frameToMs(frame, fps), visual.end_ms - visual.start_ms - 1);
  return (
    <AbsoluteFill style={{ background: '#0a0f1f' }}>
      <ScenePanel active={{ visual, t, opacity: 1, enter: 1 }} cast={cast} mediaBase={mediaBase} w={POSTER_W} h={POSTER_H} k={1} />
    </AbsoluteFill>
  );
};
