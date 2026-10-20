import { Player, Thumbnail } from '@remotion/player';
import { absoluteMediaBase } from '../../api/media';
import type { TimelineVisual } from '../../api/visuals';
import { FPS, POSTER_H, POSTER_W } from '../../video/constants';
import { ScenePoster } from '../../video/ScenePoster';
import { msToFrame } from '../../video/timing';
import type { SceneCast } from '../../video/visuals/SceneStage';

/** The scene board's Remotion parts: a scene's last frame as a still, and the scene replayed in a
 *  loop. Browser-only: TurnScenes loads them lazily. */

interface Props {
  visual: TimelineVisual;
  cast: SceneCast;
  /** The media folder (relative or absolute): pictures of the scenes. */
  mediaBase: string;
}

const sceneFrames = (visual: TimelineVisual) => Math.max(2, msToFrame(visual.end_ms - visual.start_ms));

export const SceneThumbnail = ({ visual, cast, mediaBase }: Props) => {
  const frames = sceneFrames(visual);
  return <Thumbnail component={ScenePoster} compositionWidth={POSTER_W} compositionHeight={POSTER_H} durationInFrames={frames} frameToDisplay={frames - 1} fps={FPS} inputProps={{ visual, cast, mediaBase: absoluteMediaBase(mediaBase) }} style={{ width: '100%', height: '100%' }} />;
};

export const ScenePlayer = ({ visual, cast, mediaBase }: Props) => (
  <Player component={ScenePoster} compositionWidth={POSTER_W} compositionHeight={POSTER_H} durationInFrames={sceneFrames(visual) + msToFrame(800)} fps={FPS} inputProps={{ visual, cast, mediaBase: absoluteMediaBase(mediaBase) }} style={{ width: '100%' }} autoPlay loop controls />
);
