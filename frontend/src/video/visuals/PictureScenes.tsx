import { Img } from 'remotion';
import type { ImageScene, SketchScene } from '../../api/visuals';
import { FONT, MONO_FONT } from '../constants';
import { INK, clamp01, easeInOut, easeOut, fitFont, ramp, seedOf } from './draw';
import { Reveal, Stroke } from './Ink';
import type { SceneCtx } from './scene';

const LINE_PX = 4.2; // marker width on the 16:9 stage

/** When each stroke starts and how long it takes: proportional to its path length. */
const strokeSpans = (paths: string[], drawMs: number): { start: number; len: number }[] => {
  const weights = paths.map((d) => Math.max(24, d.length));
  const total = weights.reduce((a, b) => a + b, 0);
  const spans: { start: number; len: number }[] = [];
  let acc = 0;
  for (const wt of weights) {
    spans.push({ start: 150 + (acc / total) * drawMs, len: Math.max(120, (wt / total) * drawMs) });
    acc += wt;
  }
  return spans;
};

/** A hand-drawn illustration: the server-sanitized strokes ink in one after another, longer
 *  lines taking longer; closed shapes get a light wash once drawn. */
export const SketchView = ({ scene, ctx }: { scene: SketchScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, dur } = ctx;
  const drawing = scene.drawing;
  if (!drawing || drawing.strokes.length === 0) return null;
  const [vx, vy, vw, vh] = drawing.view;
  const capH = scene.caption ? 70 * k : 0;
  const boxH = Math.max(1, h - capH);
  const scale = Math.min(w / vw, boxH / vh);
  const dw = vw * scale;
  const dh = vh * scale;
  const drawMs = Math.min(3600, Math.max(1600, dur * 0.5));
  const spans = strokeSpans(drawing.strokes.map((s) => s.d), drawMs);
  const width = (LINE_PX * k) / scale; // in drawing units, so every sketch gets the same marker
  return (
    <>
      <svg width={Math.max(1, dw)} height={Math.max(1, dh)} viewBox={`${vx} ${vy} ${vw} ${vh}`} style={{ position: 'absolute', left: (w - dw) / 2, top: (boxH - dh) / 2, display: 'block', overflow: 'visible' }}>
        {drawing.strokes.map((s, i) => {
          const c = s.accent ? color : INK;
          const { start, len } = spans[i];
          const wash = s.fill ? easeOut(ramp(t, start + len, 450)) : 0;
          return (
            <g key={i} transform={s.t || undefined}>
              {wash > 0 && <path d={s.d} fill={c} fillOpacity={0.18 * wash} stroke="none" />}
              <Stroke d={s.d} p={easeInOut(ramp(t, start, len))} color={c} width={width * s.w} />
            </g>
          );
        })}
      </svg>
      {scene.caption && (
        <Reveal p={easeOut(ramp(t, drawMs * 0.6, 500))} dy={10 * k} style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: capH, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', fontFamily: FONT, fontWeight: 700, fontSize: fitFont(scene.caption, w * 0.9, 1, 40 * k, 24 * k), color: INK }}>
          {scene.caption}
        </Reveal>
      )}
    </>
  );
};

/** A photo or AI picture with a slow Ken Burns zoom; the credit stays in the corner. */
export const ImageView = ({ scene, ctx }: { scene: ImageScene; ctx: SceneCtx }) => {
  const { t, w, h, k, dur, id, mediaBase } = ctx;
  if (!scene.src || !mediaBase) return null;
  const capH = scene.caption ? 64 * k : 0;
  const imgH = Math.max(1, h - capH);
  const progress = clamp01(t / Math.max(1, dur));
  const zoom = 1.03 + 0.09 * easeInOut(progress);
  const dir = seedOf(id) % 2 === 0 ? 1 : -1;
  const credit = scene.credit || (scene.kind === 'ai' ? 'AI-generated image' : '');
  return (
    <>
      <div style={{ position: 'absolute', left: 0, top: 0, width: w, height: imgH, borderRadius: 22 * k, overflow: 'hidden', background: '#0b1022', opacity: easeOut(ramp(t, 0, 450)) }}>
        <Img src={`${mediaBase}/${scene.src}`} style={{ width: w, height: imgH, objectFit: 'cover', display: 'block', transform: `scale(${zoom}) translate(${dir * 2.2 * progress}%, ${-1.2 * progress}%)` }} />
        {credit && (
          <div style={{ position: 'absolute', right: 12 * k, bottom: 10 * k, maxWidth: w * 0.7, padding: `${4 * k}px ${10 * k}px`, borderRadius: 8 * k, background: '#000000a6', fontFamily: MONO_FONT, fontSize: 15 * k, lineHeight: 1.3, color: '#ffffffd9', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {credit}
          </div>
        )}
      </div>
      {scene.caption && (
        <Reveal p={easeOut(ramp(t, 350, 450))} dy={10 * k} style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: capH, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', fontFamily: FONT, fontWeight: 700, fontSize: fitFont(scene.caption, w * 0.9, 1, 38 * k, 24 * k), color: INK }}>
          {scene.caption}
        </Reveal>
      )}
    </>
  );
};
