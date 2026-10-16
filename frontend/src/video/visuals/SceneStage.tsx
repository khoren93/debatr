import { useEffect } from 'react';
import type { Timeline, TimelineSegment } from '../../api/timeline';
import type { Scene } from '../../api/visuals';
import { DISPLAY_FONT, FONT, MONO_FONT } from '../constants';
import { Mascot } from '../Mascot';
import { levelAt, roundLabel } from '../utils';
import { DefinitionView, RankingView, ScoreboardView } from './CardScenes';
import { MatrixView, ScaleView, VennView } from './DiagramScenes';
import { INK, INK_DIM, fitFont } from './draw';
import { hasMapScene, loadGeo } from './geoLoader';
import { MapView } from './MapView';
import { BarsView, LineView, PieView, ProportionView, StatView } from './NumberScenes';
import { FlowView, IconsView, TimelineView } from './SchemeScenes';
import type { SceneCtx } from './scene';
import { BulletsView, HeadlineView, QuoteView, RebuttalView, VersusView } from './TextScenes';
import { relativeItems, scenesAt, type ActiveScene } from './timing';

const NUMERIC = new Set<Scene['type']>(['stat', 'bars', 'line', 'pie', 'proportion']);
const UNTITLED = new Set<Scene['type']>(['headline', 'quote', 'definition', 'scoreboard']);

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
    default:
      return null; // a scene type from a newer timeline
  }
};

/** The board a scene is drawn on: panel, speaker tag, title, "claim" note for numbers. */
const ScenePanel = ({ active, timeline, w, h, k }: { active: ActiveScene; timeline: Timeline; w: number; h: number; k: number }) => {
  const { visual, t, opacity, enter } = active;
  const scene = visual.scene;
  const speaker = timeline.speakers.find((s) => s.id === visual.speaker_id);
  const color = speaker?.color ?? INK;
  const title = UNTITLED.has(scene.type) ? '' : scene.title;
  const numeric = isNumeric(scene);
  const pad = 44 * k;
  const head = title ? 78 * k : 34 * k;
  const foot = numeric ? 40 * k : 0;
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
    locale: timeline.language_code,
    cast: timeline.speakers,
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
      {numeric && <div style={{ position: 'absolute', left: pad, bottom: 22 * k, fontFamily: MONO_FONT, fontSize: 18 * k, letterSpacing: 1 * k, color: INK_DIM }}>claim · {speaker?.name}</div>}
    </div>
  );
};

const turnLabel = (seg: TimelineSegment) => {
  const kind = seg.turn_type.replace(/_/g, ' ');
  return seg.round_id === 'verdict' ? 'Verdict' : `${kind} · ${roundLabel(seg.round_id)}`;
};

/** Idle stage: the topic (no one speaking / the host) or the speaking character in big. */
const Spotlight = ({ timeline, seg, ms, w, h, k }: { timeline: Timeline; seg: TimelineSegment | null; ms: number; w: number; h: number; k: number }) => {
  const speaker = seg ? timeline.speakers.find((s) => s.id === seg.speaker_id) : null;
  if (!seg || !speaker || speaker.role === 'moderator') {
    const topicFs = fitFont(timeline.topic, w * 0.86, 3, 76 * k, 40 * k);
    return (
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 22 * k, padding: `0 ${w * 0.07}px`, textAlign: 'center', fontFamily: FONT }}>
        {seg && <div style={{ fontSize: 26 * k, fontWeight: 800, letterSpacing: 6 * k, textTransform: 'uppercase', color: '#FFC46B' }}>{roundLabel(seg.round_id)}</div>}
        <div style={{ fontFamily: DISPLAY_FONT, fontSize: topicFs, fontWeight: 800, lineHeight: 1.1, color: INK, textShadow: '0 6px 30px #0009' }}>{timeline.topic}</div>
      </div>
    );
  }
  const size = Math.min(h * 0.5, 330 * k);
  const level = levelAt(seg, ms);
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16 * k, fontFamily: FONT, textAlign: 'center' }}>
      <div style={{ position: 'relative', width: size, height: size, transform: `scale(${1 + level * 0.04})` }}>
        <div style={{ position: 'absolute', left: -size * 0.35, top: -size * 0.35, width: size * 1.7, height: size * 1.7, background: `radial-gradient(circle, ${speaker.color}${level > 0.3 ? '55' : '38'} 0%, transparent 62%)` }} />
        <div style={{ position: 'absolute', inset: 0 }}>
          <Mascot kind={speaker.mascot} color={speaker.color} size={size} mouth={level} talking />
        </div>
      </div>
      <div style={{ fontFamily: DISPLAY_FONT, fontSize: 64 * k, fontWeight: 800, lineHeight: 1.05, color: speaker.color }}>{speaker.name}</div>
      <div style={{ fontSize: 24 * k, fontWeight: 700, letterSpacing: 4 * k, textTransform: 'uppercase', color: INK_DIM }}>{turnLabel(seg)}</div>
    </div>
  );
};

/** Centre of the frame: the active visual scene(s), or the spotlight between scenes. */
export const SceneStage = ({ timeline, seg, ms, x, y, w, h, k }: { timeline: Timeline; seg: TimelineSegment | null; ms: number; x: number; y: number; w: number; h: number; k: number }) => {
  const { active, cover } = scenesAt(timeline.visuals, ms);
  const needsMap = hasMapScene(timeline);
  useEffect(() => {
    if (needsMap) void loadGeo().catch(() => undefined); // warm up before the first map scene
  }, [needsMap]);
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: w, height: h }}>
      {cover < 1 && (
        <div style={{ position: 'absolute', inset: 0, opacity: 1 - cover }}>
          <Spotlight timeline={timeline} seg={seg} ms={ms} w={w} h={h} k={k} />
        </div>
      )}
      {active.map((a) => (
        <ScenePanel key={a.visual.id} active={a} timeline={timeline} w={w} h={h} k={k} />
      ))}
    </div>
  );
};
