import type { BulletsScene, HeadlineScene, QuoteScene, RebuttalScene, VersusScene } from '../../api/visuals';
import { DISPLAY_FONT, FONT } from '../constants';
import { INK, INK_DIM, backOut, easeOut, fitFont, ramp, seedOf, sketch, type Pt } from './draw';
import { InkLayer, Reveal, Stroke } from './Ink';
import { seriesColors, type SceneCtx } from './scene';

const STRIKE = '#FF7A66';

/** Key points ticked off one by one as they are said. */
export const BulletsView = ({ scene, ctx }: { scene: BulletsScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, id } = ctx;
  const seed = seedOf(id);
  const n = scene.items.length;
  const rowH = Math.min(170 * k, h / n);
  const top = (h - rowH * n) / 2;
  const box = 54 * k;
  const textLeft = box + 40 * k;
  const fs = Math.min(n > 3 ? 40 * k : 46 * k, Math.min(...scene.items.map((i) => fitFont(i.text, w - textLeft, 2, 60 * k, 26 * k))));
  const current = items.reduce((cur, at, i) => (t >= at ? i : cur), 0);
  return (
    <>
      <InkLayer w={w} h={h}>
        {scene.items.map((_, i) => {
          const y = top + rowH * i + (rowH - box) / 2;
          return <Stroke key={i} d={sketch.check(6 * k, y, box * 0.9, seed + i)} p={easeOut(ramp(t, (items[i] ?? 0) + 120, 400))} color={color} width={8 * k} />;
        })}
      </InkLayer>
      {scene.items.map((item, i) => (
        <Reveal
          key={i}
          p={easeOut(ramp(t, items[i] ?? 0, 380))}
          dy={14 * k}
          style={{ position: 'absolute', left: textLeft, right: 0, top: top + rowH * i, height: rowH, display: 'flex', alignItems: 'center', fontFamily: FONT, fontWeight: 700, fontSize: fs, lineHeight: 1.18, color: i === current ? INK : '#ffffffa8' }}
        >
          {item.text}
        </Reveal>
      ))}
    </>
  );
};

/** Two columns (A vs B, pros vs cons) filled in turn, split by a hand-drawn line. */
export const VersusView = ({ scene, ctx }: { scene: VersusScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, dur, id } = ctx;
  const seed = seedOf(id);
  const [left, right] = seriesColors(color, 2);
  const colW = w * 0.43;
  const headH = 76 * k;
  const maxItems = Math.max(scene.left.items.length, scene.right.items.length);
  const rowH = Math.min(118 * k, (h - headH - 20 * k) / maxItems);
  const order: { side: 'left' | 'right'; i: number }[] = [];
  for (let i = 0; i < maxItems; i++) {
    if (i < scene.left.items.length) order.push({ side: 'left', i });
    if (i < scene.right.items.length) order.push({ side: 'right', i });
  }
  const step = Math.max(350, Math.min(1100, (dur * 0.6 - 600) / Math.max(1, order.length)));
  const at = (side: 'left' | 'right', i: number) => 600 + order.findIndex((o) => o.side === side && o.i === i) * step;
  const all = [...scene.left.items, ...scene.right.items];
  const fs = Math.min(32 * k, Math.min(...all.map((s) => fitFont(s, colW - 44 * k, 2, 40 * k, 22 * k))));
  const column = (side: 'left' | 'right', x: number, c: string) => {
    const data = scene[side];
    return (
      <>
        <Reveal p={easeOut(ramp(t, side === 'left' ? 0 : 200, 400))} style={{ position: 'absolute', left: x, width: colW, top: 0, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: 42 * k, color: c, whiteSpace: 'nowrap', overflow: 'hidden' }}>
          {data.label}
        </Reveal>
        {data.items.map((text, i) => (
          <Reveal key={i} p={easeOut(ramp(t, at(side, i), 380))} dy={10 * k} style={{ position: 'absolute', left: x + 40 * k, width: colW - 44 * k, top: headH + rowH * i, height: rowH, display: 'flex', alignItems: 'center', fontFamily: FONT, fontWeight: 600, fontSize: fs, lineHeight: 1.18, color: INK }}>
            {text}
          </Reveal>
        ))}
      </>
    );
  };
  const rightX = w - colW;
  return (
    <>
      <InkLayer w={w} h={h}>
        <Stroke d={sketch.line([w / 2, 6 * k], [w / 2, h - 6 * k], seed, { roughness: 1.4, bowing: 1.5 })} p={easeOut(ramp(t, 0, 600))} color={INK_DIM} width={4 * k} />
        <Stroke d={sketch.line([0, headH - 18 * k], [colW * 0.7, headH - 14 * k], seed + 1, { roughness: 1.3 })} p={easeOut(ramp(t, 250, 450))} color={left} width={5 * k} />
        <Stroke d={sketch.line([rightX, headH - 18 * k], [rightX + colW * 0.7, headH - 14 * k], seed + 2, { roughness: 1.3 })} p={easeOut(ramp(t, 450, 450))} color={right} width={5 * k} />
        {(['left', 'right'] as const).flatMap((side) =>
          scene[side].items.map((_, i) => {
            const x = side === 'left' ? 4 * k : rightX + 4 * k;
            const y = headH + rowH * i + rowH / 2;
            return <Stroke key={`${side}${i}`} d={sketch.line([x, y], [x + 22 * k, y], seed + 10 + i + (side === 'left' ? 0 : 20), { roughness: 0.8 })} p={easeOut(ramp(t, at(side, i), 250))} color={side === 'left' ? left : right} width={6 * k} />;
          }),
        )}
      </InkLayer>
      {column('left', 0, left)}
      {column('right', rightX, right)}
    </>
  );
};

/** Quotation: a big quote mark, words inked in reading order, the author underlined. */
export const QuoteView = ({ scene, ctx }: { scene: QuoteScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, id } = ctx;
  const seed = seedOf(id);
  const words = scene.text.split(/\s+/);
  const fs = fitFont(scene.text, w * 0.86, 4, 64 * k, 34 * k);
  const shown = Math.ceil(easeOut(ramp(t, 250, Math.min(2400, words.length * 110))) * words.length);
  const authorAt = 400 + Math.min(2400, words.length * 110);
  return (
    <>
      <div style={{ position: 'absolute', left: 0, top: -40 * k, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: 200 * k, lineHeight: 1, color, opacity: easeOut(ramp(t, 0, 400)), transform: `scale(${0.7 + 0.3 * backOut(ramp(t, 0, 450))})`, transformOrigin: 'left top' }}>“</div>
      <InkLayer w={w} h={h}>
        {scene.author && <Stroke d={sketch.line([w * 0.52, h - 22 * k], [w - 10 * k, h - 18 * k], seed + 5, { roughness: 1.2 })} p={easeOut(ramp(t, authorAt + 200, 500))} color={color} width={4 * k} />}
      </InkLayer>
      <div style={{ position: 'absolute', left: w * 0.07, right: w * 0.05, top: 90 * k, bottom: scene.author ? 90 * k : 20 * k, display: 'flex', alignItems: 'center', fontFamily: DISPLAY_FONT, fontWeight: 700, fontSize: fs, lineHeight: 1.22, color: INK }}>
        <div>
          {words.map((word, i) => (
            <span key={i} style={{ opacity: i < shown ? 1 : 0.12 }}>
              {word}{' '}
            </span>
          ))}
        </div>
      </div>
      {scene.author && (
        <Reveal p={easeOut(ramp(t, authorAt, 400))} style={{ position: 'absolute', right: 10 * k, bottom: 30 * k, fontFamily: FONT, fontWeight: 700, fontSize: 32 * k, color }}>
          — {scene.author}
        </Reveal>
      )}
    </>
  );
};

/** The opponent's claim gets struck through on the reply's phrase, then the reply lands. */
export const RebuttalView = ({ scene, ctx }: { scene: RebuttalScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, dur, id } = ctx;
  const seed = seedOf(id);
  const reply = items[1] ?? dur * 0.45;
  const claimW = w * 0.92;
  const fs = fitFont(scene.claim, claimW, 3, 46 * k, 28 * k);
  const claimTop = 46 * k;
  const est = scene.claim.length * fs * 0.5;
  const lines = Math.max(1, Math.min(3, Math.ceil(est / claimW)));
  const struck = ramp(t, reply, 300 + lines * 200);
  const replyTop = Math.max(h * 0.5, claimTop + lines * fs * 1.25 + 60 * k);
  const replyFs = fitFont(scene.response, w * 0.84, 2, 60 * k, 32 * k);
  const arrowFrom: Pt = [30 * k, replyTop - 40 * k];
  const arrowTo: Pt = [70 * k, replyTop + replyFs * 0.6];
  return (
    <>
      <InkLayer w={w} h={h}>
        {Array.from({ length: lines }).map((_, i) => {
          const y = claimTop + i * fs * 1.25 + fs * 0.66;
          const len = i < lines - 1 ? claimW : Math.max(fs * 3, Math.min(claimW, est - i * claimW));
          return <Stroke key={i} d={sketch.line([-6 * k, y + 4 * k], [len + 6 * k, y - 6 * k], seed + i, { roughness: 1.8, bowing: 1.2 })} p={easeOut(ramp(t, reply + i * 200, 320))} color={STRIKE} width={7 * k} />;
        })}
        <Stroke d={sketch.arc(arrowFrom, [arrowFrom[0] - 4 * k, arrowTo[1] - 10 * k], arrowTo, seed + 9, 20 * k)} p={easeOut(ramp(t, reply + 250, 400))} color={color} width={6 * k} />
      </InkLayer>
      <div style={{ position: 'absolute', left: 0, top: 0, fontFamily: FONT, fontWeight: 700, fontSize: 24 * k, letterSpacing: 3 * k, textTransform: 'uppercase', color: INK_DIM }}>{scene.claim_author || 'Opponent'}</div>
      <div style={{ position: 'absolute', left: 0, width: claimW, top: claimTop, fontFamily: FONT, fontWeight: 700, fontSize: fs, lineHeight: 1.25, color: INK, opacity: 1 - struck * 0.5 }}>{scene.claim}</div>
      <Reveal p={easeOut(ramp(t, reply + 350, 450))} dy={20 * k} style={{ position: 'absolute', left: 110 * k, right: 0, top: replyTop, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: replyFs, lineHeight: 1.15, color }}>
        {scene.response}
      </Reveal>
    </>
  );
};

const bare = (word: string) => word.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');

/** Kinetic typography: the punchline slams in word by word, key words marker-highlighted. */
export const HeadlineView = ({ scene, ctx }: { scene: HeadlineScene; ctx: SceneCtx }) => {
  const { t, w, k, color } = ctx;
  const words = scene.text.split(/\s+/).filter(Boolean);
  const emphasis = new Set(scene.emphasis.split(/\s+/).map(bare).filter(Boolean));
  const fs = fitFont(scene.text, w * 0.9, scene.text.length > 30 ? 3 : 2, 116 * k, 54 * k);
  const done = 120 + words.length * 130 + 300;
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: `0 ${w * 0.04}px` }}>
      <div style={{ textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: fs, lineHeight: 1.12, color: INK, letterSpacing: -fs * 0.015 }}>
        {words.map((word, i) => {
          const p = ramp(t, 120 + i * 130, 320);
          const hot = emphasis.has(bare(word));
          const swipe = easeOut(ramp(t, done + i * 60, 380));
          return (
            <span key={i} style={{ display: 'inline-block', position: 'relative', marginRight: '0.24em', opacity: p > 0 ? Math.min(1, p * 2) : 0, transform: `scale(${1.5 - 0.5 * backOut(p)})`, color: hot ? color : INK }}>
              {hot && <span style={{ position: 'absolute', left: '-0.06em', bottom: '0.14em', height: '0.34em', width: `${swipe * 104}%`, background: `${color}40`, borderRadius: '0.08em' }} />}
              <span style={{ position: 'relative' }}>{word}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
};
