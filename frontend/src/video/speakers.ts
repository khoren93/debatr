import type { TimelineSpeaker } from '../api/timeline';

/** Full model id of a speaker (timelines built before `model_id` only carry the short name). */
export const speakerModelId = (s: Pick<TimelineSpeaker, 'model' | 'model_id'>) => s.model_id || s.model;

/** PRO / CON (two debaters) or PRO / CON / SIDE 3… */
export const debaterTag = (speaker: TimelineSpeaker, debaters: TimelineSpeaker[]) => {
  const i = debaters.findIndex((d) => d.id === speaker.id);
  return i === 0 ? 'PRO' : i === 1 ? 'CON' : `SIDE ${i + 1}`;
};
