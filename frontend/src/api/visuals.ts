// Mirrors backend/app/schemas/visuals.py (timeline.json → visuals[]): typed scene data drawn by
// src/video/visuals/. Icons are keys of ICONS in src/video/visuals/icons.ts.

interface SceneBase {
  anchor: string;
  until: string;
  title: string;
}

export interface ScenePoint {
  label: string;
  value: number;
  highlight: boolean;
}

export interface StatScene extends SceneBase {
  type: 'stat';
  value: number;
  prefix: string;
  suffix: string;
  label: string;
  trend: 'up' | 'down' | null;
  icon: string | null;
}

export interface BarsScene extends SceneBase {
  type: 'bars';
  unit: string;
  items: ScenePoint[];
}

export interface LineScene extends SceneBase {
  type: 'line';
  unit: string;
  points: ScenePoint[];
}

export interface PieScene extends SceneBase {
  type: 'pie';
  unit: string;
  items: ScenePoint[];
}

export interface ProportionScene extends SceneBase {
  type: 'proportion';
  count: number;
  total: number;
  label: string;
  icon: string | null;
}

export interface BulletsScene extends SceneBase {
  type: 'bullets';
  items: { text: string; anchor: string }[];
}

export interface VersusScene extends SceneBase {
  type: 'versus';
  left: { label: string; items: string[] };
  right: { label: string; items: string[] };
}

export interface QuoteScene extends SceneBase {
  type: 'quote';
  text: string;
  author: string;
}

export interface RebuttalScene extends SceneBase {
  type: 'rebuttal';
  claim: string;
  claim_author: string;
  response: string;
  response_anchor: string;
}

export interface HeadlineScene extends SceneBase {
  type: 'headline';
  text: string;
  emphasis: string;
}

export interface FlowScene extends SceneBase {
  type: 'flow';
  layout: 'chain' | 'cycle';
  steps: { label: string; icon: string | null; anchor: string }[];
}

export interface TimelineScene extends SceneBase {
  type: 'timeline';
  events: { date: string; label: string; anchor: string }[];
}

export interface IconsScene extends SceneBase {
  type: 'icons';
  items: { icon: string; label: string; anchor: string }[];
}

export interface ScaleScene extends SceneBase {
  type: 'scale';
  left: { label: string; items: { text: string; anchor: string }[] };
  right: { label: string; items: { text: string; anchor: string }[] };
  heavier: 'left' | 'right' | 'even' | null; // null: by the number of arguments
}

export interface MatrixScene extends SceneBase {
  type: 'matrix';
  x_axis: string;
  y_axis: string;
  quadrants: string[]; // [] or [top-left, top-right, bottom-left, bottom-right]
  items: { label: string; x: number; y: number; highlight: boolean; anchor: string }[]; // 0..10
}

export interface VennScene extends SceneBase {
  type: 'venn';
  sets: { label: string; anchor: string }[];
  overlap: string;
  overlap_anchor: string;
}

export interface RankingScene extends SceneBase {
  type: 'ranking';
  layout: 'list' | 'pyramid';
  unit: string;
  items: { label: string; value: number | null; anchor: string }[]; // #1 first
}

export interface DefinitionScene extends SceneBase {
  type: 'definition';
  term: string;
  kind: string;
  text: string;
  source: string;
}

export interface MapScene extends SceneBase {
  type: 'map';
  unit: string;
  regions: { codes: string[]; label: string; value: number | null; anchor: string }[]; // ISO alpha-3
}

/** The judge's result, built from the structured verdict (not by the director). */
export interface ScoreboardScene extends SceneBase {
  type: 'scoreboard';
  speaker_ids: string[];
  winner_id: string | null; // null: a draw
  headline: string;
}

export type Scene =
  | StatScene
  | BarsScene
  | LineScene
  | PieScene
  | ProportionScene
  | BulletsScene
  | VersusScene
  | QuoteScene
  | RebuttalScene
  | HeadlineScene
  | FlowScene
  | TimelineScene
  | IconsScene
  | ScaleScene
  | MatrixScene
  | VennScene
  | RankingScene
  | DefinitionScene
  | MapScene
  | ScoreboardScene;

export type SceneType = Scene['type'];

export interface TimelineVisual {
  id: string;
  seq_index: number;
  speaker_id: string;
  start_ms: number; // absolute on the full track
  end_ms: number;
  item_ms: number[]; // absolute reveal time per element (in the order of the scene's lists)
  anchored: boolean; // false: the phrase was not found, the timing is estimated
  scene: Scene;
}
