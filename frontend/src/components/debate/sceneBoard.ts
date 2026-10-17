import type { Timeline, TimelineSpeaker } from '../../api/timeline';
import type { Participant, TurnVisuals } from '../../api/types';
import type { CheckVerdict, Scene, SceneCheck, SceneDispute, TimelineVisual } from '../../api/visuals';
import { HOST_COLOR, JUDGE_COLOR, shortModelName, speakerColor } from '../../lib/format';
import type { SceneCast } from '../../video/visuals/SceneStage';

/** Helpers of the transcript's scene board (TurnScenes). */

export const TYPE_LABELS: Record<Scene['type'], string> = {
  stat: 'Number',
  bars: 'Bar chart',
  line: 'Trend',
  pie: 'Shares',
  proportion: 'Proportion',
  bullets: 'Key points',
  versus: 'Comparison',
  quote: 'Quote',
  rebuttal: 'Rebuttal',
  headline: 'Headline',
  flow: 'Cause and effect',
  timeline: 'Timeline',
  icons: 'Pictograms',
  scale: 'Balance',
  matrix: 'Matrix',
  venn: 'Overlap',
  ranking: 'Ranking',
  definition: 'Definition',
  map: 'Map',
  sketch: 'Sketch',
  image: 'Picture',
  scoreboard: 'Result',
};

export const CHECK_STYLES: Record<CheckVerdict, { label: string; className: string }> = {
  verified: { label: 'Fact-checked', className: 'border-ok/40 bg-ok/15 text-ok' },
  disputed: { label: 'Contradicted by sources', className: 'border-con/40 bg-con/15 text-con' },
  unverified: { label: 'Unverified', className: 'border-line-3 bg-surface-2 text-muted' },
};

const LIVE_SCENE_MS = 9000;

/** Elements revealed one by one (mirrors item_anchors in backend schemas/visuals.py). */
const itemCount = (scene: Scene): number => {
  switch (scene.type) {
    case 'bullets':
    case 'icons':
    case 'matrix':
    case 'ranking':
      return scene.items.length;
    case 'flow':
      return scene.steps.length;
    case 'timeline':
      return scene.events.length;
    case 'rebuttal':
      return 2;
    case 'scale':
      return scene.left.items.length + scene.right.items.length;
    case 'venn':
      return scene.sets.length + (scene.overlap ? 1 : 0);
    case 'map':
      return scene.regions.length;
    default:
      return 0;
  }
};

/** A live scene (no audio yet) as a stand-alone visual: elements revealed at an even pace. */
export const liveVisual = (seq: number, speakerId: string, key: string, scene: Scene, check: SceneCheck | null): TimelineVisual => {
  const n = itemCount(scene);
  const step = Math.min(900, 4800 / Math.max(1, n));
  return {
    id: `live_${key.replace(/[^\w-]/g, '_')}`,
    seq_index: seq,
    speaker_id: speakerId,
    start_ms: 0,
    end_ms: LIVE_SCENE_MS,
    item_ms: Array.from({ length: n }, (_, i) => 400 + i * step),
    anchored: false,
    key,
    check,
    scene,
  };
};

/** A timeline visual with its times relative to the scene start (same id: same strokes). */
export const rebase = (v: TimelineVisual): TimelineVisual => ({ ...v, start_ms: 0, end_ms: v.end_ms - v.start_ms, item_ms: v.item_ms.map((t) => Math.max(0, t - v.start_ms)) });

/** Speakers for scenes shown outside the video (colours as in lib/format). */
export const sceneCast = (participants: Participant[], timeline: Timeline | null, languageCode: string): SceneCast => {
  if (timeline) return timeline;
  const speakers: TimelineSpeaker[] = participants.map((p, i) => {
    const id = p.id ?? `participant_${i}`;
    const role = p.role === 'moderator' ? 'moderator' : 'debater';
    return { id, name: p.name ?? `Speaker ${i + 1}`, role, model: shortModelName(p.model), model_id: p.model, color: role === 'moderator' ? HOST_COLOR : speakerColor(id, participants), mascot: 'orb', avatar_url: null, voice_id: null };
  });
  speakers.push({ id: 'judge', name: 'Judge', role: 'judge', model: '', color: JUDGE_COLOR, mascot: 'cube', avatar_url: null, voice_id: null });
  return { speakers, language_code: languageCode };
};

/** Every challenge made in the debate, by the key of the challenged scene. */
export const disputesByKey = (turns: { seq_index: number; speaker_id?: string; speaker_name: string; visuals?: TurnVisuals | null }[]): Map<string, SceneDispute[]> => {
  const out = new Map<string, SceneDispute[]>();
  for (const turn of turns) {
    for (const d of turn.visuals?.disputes ?? []) {
      const list = out.get(d.key) ?? [];
      list.push({ by_id: turn.speaker_id ?? '', by_name: turn.speaker_name, seq_index: turn.seq_index, reason: d.reason });
      out.set(d.key, list);
    }
  }
  return out;
};
