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
  | IconsScene;

export type SceneType = Scene['type'];

export interface TimelineVisual {
  id: string;
  seq_index: number;
  speaker_id: string;
  start_ms: number; // absolute on the full track
  end_ms: number;
  item_ms: number[]; // absolute reveal time per element (bullets, steps, events, rebuttal)
  anchored: boolean; // false: the phrase was not found, the timing is estimated
  scene: Scene;
}
