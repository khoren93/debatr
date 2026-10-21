import type { ScoreboardScene } from '../api/visuals';

/** When a scoreboard shows its parts, ms after the scene appears (no Remotion): the score sheet's
 *  rows and the moment the winner is crowned, which the crowd's roar follows (video/sfx.ts). */

/** A battle's score sheet reveals a row (a round, then the totals) every 550 ms. */
export const sheetRowAt = (i: number): number => 600 + i * 550;

/** The winner is crowned: on the sheet when the judge calls the result (`decide_ms`), never
 *  before the totals; on the plain board after every debater has come in. */
export const winnerRevealMs = (scene: ScoreboardScene): number =>
  scene.rounds?.length ? Math.max(sheetRowAt(scene.rounds.length) + 500, scene.decide_ms ?? 0) : 700 + Math.max(1, scene.speaker_ids.length) * 250;
