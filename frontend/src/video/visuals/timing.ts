import type { TimelineVisual } from '../../api/visuals';
import { easeOut, ramp } from './draw';

export const SCENE_IN_MS = 380;
export const SCENE_OUT_MS = 320;
/** Two scenes closer than this keep the stage covered (no spotlight flash in between). */
const BRIDGE_MS = 900;

export interface ActiveScene {
  visual: TimelineVisual;
  t: number; // ms since the scene appeared
  opacity: number;
  enter: number; // 0..1 entrance progress (for the slide-in)
}

/** Scenes visible at `ms` (two during a cross-fade) and how much they cover the stage. */
export const scenesAt = (visuals: TimelineVisual[] | undefined, ms: number): { active: ActiveScene[]; cover: number } => {
  const list = visuals ?? [];
  const active: ActiveScene[] = [];
  let prevEnd = -Infinity;
  let nextStart = Infinity;
  for (const v of list) {
    if (v.end_ms <= ms) prevEnd = Math.max(prevEnd, v.end_ms);
    if (v.start_ms > ms) nextStart = Math.min(nextStart, v.start_ms);
    if (ms < v.start_ms || ms >= v.end_ms + SCENE_OUT_MS) continue;
    const enter = easeOut(ramp(ms, v.start_ms, SCENE_IN_MS));
    const exit = 1 - ramp(ms, v.end_ms, SCENE_OUT_MS);
    active.push({ visual: v, t: ms - v.start_ms, opacity: Math.min(enter, exit), enter });
  }
  let cover = Math.max(0, ...active.map((a) => a.opacity));
  if (nextStart - prevEnd < BRIDGE_MS) cover = 1;
  return { active, cover };
};

/** Relative reveal times of a scene's elements. */
export const relativeItems = (v: TimelineVisual): number[] => v.item_ms.map((at) => Math.max(0, at - v.start_ms));
