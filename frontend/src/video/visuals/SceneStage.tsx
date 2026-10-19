import { useEffect } from 'react';
import type { Timeline, TimelineSegment } from '../../api/timeline';
import type { Scene, SceneCheck, SceneDispute } from '../../api/visuals';
import { DISPLAY_FONT, FONT, MONO_FONT } from '../constants';
import { roundLabel } from '../utils';
import { DefinitionView, RankingView, ScoreboardView } from './CardScenes';
import { MatrixView, ScaleView, VennView } from './DiagramScenes';
import { INK, INK_DIM, backOut, easeOut, fitFont, ramp } from './draw';
import { hasMapScene, loadGeo } from './geoLoader';
import { MapView } from './MapView';
import { BarsView, LineView, PieView, ProportionView, StatView } from './NumberScenes';
import { ImageView, SketchView } from './PictureScenes';
import { FlowView, IconsView, TimelineView } from './SchemeScenes';
import type { SceneCtx } from './scene';
import { BulletsView, HeadlineView, QuoteView, RebuttalView, VersusView } from './TextScenes';
import { relativeItems, scenesAt, type ActiveScene } from './timing';

const NUMERIC = new Set<Scene['type']>(['stat', 'bars', 'line', 'pie', 'proportion']);
const UNTITLED = new Set<Scene['type']>(['headline', 'quote', 'definition', 'scoreboard']);
const CHECK_COLORS: Record<SceneCheck['verdict'], string> = { verified: '#34D399', disputed: '#FF7A66', unverified: '#ffffff8c' };
const DISPUTE_COLOR = '#FFB020';

/** Scenes showing numbers the speaker said get the "claim" note (they are not fact-checked). */
const isNumeric = (scene: Scene) =>
  NUMERIC.has(scene.type) || (scene.type === 'ranking' && scene.items.some((i) => i.value !== null)) || (scene.type === 'map' && scene.regions.some((r) => r.value !== null));

const SceneBody = ({ scene, ctx }: { scene: Scene; ctx: SceneCtx }) => {
  switch (scene.type) {
    case 'stat':
      return <StatView scene={scene} ctx={ctx} />;
    case 'bars':
      return <BarsView scene={scene} ctx={ctx} />;
    case 'line':
      return <LineView scene={scene} ctx={ctx} />;
    case 'pie':
      return <PieView scene={scene} ctx={ctx} />;
    case 'proportion':
      return <ProportionView scene={scene} ctx={ctx} />;
    case 'bullets':
      return <BulletsView scene={scene} ctx={ctx} />;
    case 'versus':
      return <VersusView scene={scene} ctx={ctx} />;
    case 'quote':
      return <QuoteView scene={scene} ctx={ctx} />;
    case 'rebuttal':
      return <RebuttalView scene={scene} ctx={ctx} />;
    case 'headline':
      return <HeadlineView scene={scene} ctx={ctx} />;
    case 'flow':
      return <FlowView scene={scene} ctx={ctx} />;
    case 'timeline':
      return <TimelineView scene={scene} ctx={ctx} />;
    case 'icons':
      return <IconsView scene={scene} ctx={ctx} />;
    case 'scale':
      return <ScaleView scene={scene} ctx={ctx} />;
    case 'matrix':
      return <MatrixView scene={scene} ctx={ctx} />;
    case 'venn':
      return <VennView scene={scene} ctx={ctx} />;
    case 'ranking':
      return <RankingView scene={scene} ctx={ctx} />;
    case 'definition':
      return <DefinitionView scene={scene} ctx={ctx} />;
    case 'map':
      return <MapView scene={scene} ctx={ctx} />;
    case 'scoreboard':
      return <ScoreboardView scene={scene} ctx={ctx} />;
    case 'sketch':
      return <SketchView scene={scene} ctx={ctx} />;
    case 'image':
      return <ImageView scene={scene} ctx={ctx} />;
    default:
      return null; // a scene type from a newer timeline
  }
};

const domain = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
};

/** Tiny hand-drawn tick / cross / question mark for the fact-check badge (SVG attributes only). */
const CheckMark = ({ verdict, size, color }: { verdict: SceneCheck['verdict']; size: number; color: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ display: 'block', flexShrink: 0 }}>
    {verdict === 'verified' && <path d="M4 12.5 L9.5 18 L20 6" fill="none" stroke={color} strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" />}
    {verdict === 'disputed' && <path d="M5 5 L19 19 M19 5 L5 19" fill="none" stroke={color} strokeWidth={3.2} strokeLinecap="round" />}
    {verdict === 'unverified' && <path d="M8 8.5 C8 4 16 4 16 8.5 C16 11.5 12 11.5 12 15 M12 19.5 L12 20" fill="none" stroke={color} strokeWidth={3} strokeLinecap="round" />}
  </svg>
);

/** "claim · speaker" for unchecked figures, the fact-check result once checked. */
const ClaimNote = ({ check, speaker, k, t }: { check: SceneCheck | null | undefined; speaker: string; k: number; t: number }) => {
  if (!check) return <span style={{ color: INK_DIM }}>claim · {speaker}</span>;
  const color = CHECK_COLORS[check.verdict];
  const source = check.sources[0] ? domain(check.sources[0].url) : '';
  const label = check.verdict === 'verified' ? 'fact-checked' : check.verdict === 'disputed' ? 'contradicted by sources' : 'unverified claim';
  const extra = check.verdict === 'disputed' && check.note ? check.note : source;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 * k, color, opacity: easeOut(ramp(t, 700, 500)), whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
      <CheckMark verdict={check.verdict} size={22 * k} color={color} />
      <span style={{ fontWeight: 700 }}>{label}</span>
      {extra && <span style={{ color: INK_DIM, overflow: 'hidden', textOverflow: 'ellipsis' }}>· {extra}</span>}
    </span>
  );
};

/** Stamp of the speakers who challenged the scene later in the debate. */
const DisputeStamp = ({ disputes, k, t }: { disputes: SceneDispute[]; k: number; t: number }) => {
  const names = [...new Set(disputes.map((d) => d.by_name))].join(', ');
  const p = ramp(t, 1100, 420);
  if (p <= 0) return null;
  return (
    <div style={{ position: 'absolute', right: 30 * k, bottom: 16 * k, padding: `${6 * k}px ${14 * k}px`, border: `${3 * k}px solid ${DISPUTE_COLOR}`, borderRadius: 10 * k, fontFamily: MONO_FONT, fontWeight: 800, fontSize: 18 * k, letterSpacing: 2 * k, textTransform: 'uppercase', color: DISPUTE_COLOR, background: '#0c1226e6', opacity: Math.min(1, p * 2), transform: `rotate(-4deg) scale(${1.5 - 0.5 * backOut(p)})`, whiteSpace: 'nowrap' }}>
      disputed by {names}
    </div>
  );
};

export interface SceneCast {
  speakers: Timeline['speakers'];
  language_code: string;
}

/** The board a scene is drawn on: panel, speaker tag, title, "claim" note / fact-check. */
export const ScenePanel = ({ active, cast, mediaBase, w, h, k }: { active: ActiveScene; cast: SceneCast; mediaBase: string; w: number; h: number; k: number }) => {
  const { visual, t, opacity, enter } = active;
  const scene = visual.scene;
  const speaker = cast.speakers.find((s) => s.id === visual.speaker_id);
  const color = speaker?.color ?? INK;
  const title = UNTITLED.has(scene.type) ? '' : scene.title;
  const disputes = visual.disputes ?? [];
  const note = isNumeric(scene) || Boolean(visual.check);
  const pad = 44 * k;
  const head = title ? 78 * k : 34 * k;
  const foot = note || disputes.length ? 40 * k : 0;
  const ctx: SceneCtx = {
    id: visual.id,
    t,
    dur: visual.end_ms - visual.start_ms,
    items: relativeItems(visual),
    w: w - pad * 2,
    h: h - pad * 2 - head - foot,
    k,
    color,
    speaker: speaker?.name ?? '',
    locale: cast.language_code,
    cast: cast.speakers,
    mediaBase,
  };
  return (
    <div style={{ position: 'absolute', inset: 0, opacity, transform: `translateY(${(1 - enter) * 26 * k}px) scale(${0.97 + 0.03 * enter})` }}>
      <div style={{ position: 'absolute', inset: 0, borderRadius: 36 * k, background: 'linear-gradient(180deg, #131b35f2 0%, #0c1226f2 100%)', border: `${2 * k}px solid ${color}55`, boxShadow: '0 30px 90px #00000080' }} />
      <div style={{ position: 'absolute', top: 24 * k, right: 30 * k, display: 'flex', alignItems: 'center', gap: 10 * k, fontFamily: FONT, fontWeight: 800, fontSize: 19 * k, letterSpacing: 3 * k, textTransform: 'uppercase', color }}>
        <span style={{ width: 12 * k, height: 12 * k, borderRadius: 6 * k, background: color }} />
        {speaker?.name}
      </div>
      {title && (
        <div style={{ position: 'absolute', left: pad, right: 280 * k, top: pad - 10 * k, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: fitFont(title, w - pad - 280 * k, 1, 42 * k, 28 * k), lineHeight: 1.15, color: INK, whiteSpace: 'nowrap', overflow: 'hidden' }}>{title}</div>
      )}
      <div style={{ position: 'absolute', left: pad, top: pad + head, width: ctx.w, height: ctx.h }}>
        <SceneBody scene={scene} ctx={ctx} />
      </div>
      {note && (
        <div style={{ position: 'absolute', left: pad, right: disputes.length ? w * 0.42 : pad, bottom: 22 * k, display: 'flex', fontFamily: MONO_FONT, fontSize: 18 * k, letterSpacing: 1 * k }}>
          <ClaimNote check={visual.check} speaker={speaker?.name ?? ''} k={k} t={t} />
        </div>
      )}
      {disputes.length > 0 && <DisputeStamp disputes={disputes} k={k} t={t} />}
    </div>
  );
};

/** Idle stage (no scene up): the round over the debate's question, as in the studio mockup
 *  (on the Short it sits just above the debaters' cards). */
const Spotlight = ({ timeline, seg, w, k, align }: { timeline: Timeline; seg: TimelineSegment | null; w: number; k: number; align: 'center' | 'end' }) => {
  const topicFs = fitFont(timeline.topic, w * 0.86, 3, 72 * k, 40 * k);
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: align === 'end' ? 'flex-end' : 'center', gap: 24 * k, padding: `0 ${w * 0.07}px ${align === 'end' ? 30 * k : 0}px`, textAlign: 'center' }}>
      {seg && <div style={{ fontFamily: MONO_FONT, fontSize: 23 * k, letterSpacing: 0.3 * 23 * k, color: '#FFC46B' }}>{roundLabel(seg.round_id, seg.round_label).toUpperCase()}</div>}
      <div style={{ fontFamily: DISPLAY_FONT, fontSize: topicFs, fontWeight: 800, lineHeight: 1.08, letterSpacing: -0.03 * topicFs, color: INK }}>{timeline.topic}</div>
    </div>
  );
};

/** Centre of the frame: the active visual scene(s), or the spotlight between scenes. `seg` is the
 *  turn being spoken (or the last one, during a pause). */
export const SceneStage = ({ timeline, mediaBase, seg, ms, x, y, w, h, k, idleAlign = 'center' }: { timeline: Timeline; mediaBase: string; seg: TimelineSegment | null; ms: number; x: number; y: number; w: number; h: number; k: number; idleAlign?: 'center' | 'end' }) => {
  const { active, cover } = scenesAt(timeline.visuals, ms);
  const needsMap = hasMapScene(timeline);
  useEffect(() => {
    if (needsMap) void loadGeo().catch(() => undefined); // warm up before the first map scene
  }, [needsMap]);
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: w, height: h }}>
      {cover < 1 && (
        <div style={{ position: 'absolute', inset: 0, opacity: 1 - cover }}>
          <Spotlight timeline={timeline} seg={seg} w={w} k={k} align={idleAlign} />
        </div>
      )}
      {active.map((a) => (
        <ScenePanel key={a.visual.id} active={a} cast={timeline} mediaBase={mediaBase} w={w} h={h} k={k} />
      ))}
    </div>
  );
};
