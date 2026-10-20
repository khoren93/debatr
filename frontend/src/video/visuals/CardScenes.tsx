import type { DefinitionScene, RankingScene, ScoreboardScene } from '../../api/visuals';
import { DISPLAY_FONT, FONT, MONO_FONT } from '../constants';
import { LogoTile } from '../components/ModelLogo';
import { INK, INK_DIM, backOut, compactNumber, easeInOut, easeOut, fitFont, formatNumber, ramp, seedOf, sketch, withUnit, type Pt } from './draw';
import { DrawnIcon, InkLayer, Reveal, Stroke } from './Ink';
import { seriesColors, type SceneCtx } from './scene';

/** Top list (#1 first) or a pyramid; each place appears when it is named, even in a countdown. */
export const RankingView = ({ scene, ctx }: { scene: RankingScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, items, locale, id } = ctx;
  const seed = seedOf(id);
  const n = scene.items.length;
  const at = (i: number) => items[i] ?? 300 + i * 700;
  const unit = scene.unit.length <= 3 ? scene.unit : '';
  // `like` keeps the decimals of the final value while it counts up.
  const value = (v: number | null, like = v) => (v === null ? '' : withUnit(Math.abs(like ?? v) >= 10_000 ? compactNumber(v, locale) : formatNumber(v, locale, like ?? v), unit));

  if (scene.layout === 'pyramid') {
    const colors = seriesColors(color, n);
    const th = Math.min(124 * k, (h - 8 * k) / n);
    const y0 = (h - th * n) / 2;
    const gap = 8 * k;
    const width = (level: number) => w * 0.2 + ((w * 0.92 - w * 0.2) * level) / n;
    return (
      <>
        <InkLayer w={w} h={h}>
          {scene.items.map((_, i) => {
            const top = y0 + th * i + gap / 2;
            const bottom = y0 + th * (i + 1) - gap / 2;
            const pts: Pt[] = [
              [w / 2 - width(i) / 2, top],
              [w / 2 + width(i) / 2, top],
              [w / 2 + width(i + 1) / 2, bottom],
              [w / 2 - width(i + 1) / 2, bottom],
            ];
            const shown = easeOut(ramp(t, at(i), 500));
            return (
              <g key={i}>
                <polygon points={pts.map((p) => p.join(',')).join(' ')} fill={colors[i]} fillOpacity={0.18 * shown} />
                <Stroke d={sketch.polyline([...pts, pts[0]], seed + i * 3, { roughness: 1 })} p={shown} color={colors[i]} width={4.5 * k} />
              </g>
            );
          })}
        </InkLayer>
        {scene.items.map((item, i) => {
          const room = (width(i) + width(i + 1)) / 2 - 40 * k;
          const text = item.value === null ? item.label : `${item.label} · ${value(item.value)}`;
          return (
            <Reveal key={i} p={easeOut(ramp(t, at(i) + 150, 400))} dy={10 * k} style={{ position: 'absolute', left: (w - room) / 2, width: room, top: y0 + th * i, height: th, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', fontFamily: i === 0 ? DISPLAY_FONT : FONT, fontWeight: 800, fontSize: fitFont(text, room, 2, (i === 0 ? 38 : 32) * k, 18 * k), lineHeight: 1.1, color: i === 0 ? colors[0] : INK }}>
              {text}
            </Reveal>
          );
        })}
      </>
    );
  }

  const rowH = Math.min(112 * k, h / n);
  const top = (h - rowH * n) / 2;
  const badge = Math.min(70 * k, rowH * 0.72);
  const withValues = scene.items.every((i) => i.value !== null);
  const labelLeft = badge + 30 * k;
  const barX = withValues ? w * 0.5 : w;
  const barMax = w - barX - 150 * k;
  const max = Math.max(0, ...scene.items.map((i) => i.value ?? 0)) || 1;
  const fs = Math.min(...scene.items.map((i) => fitFont(i.label, barX - labelLeft - 20 * k, 1, 40 * k, 24 * k)));
  return (
    <>
      <InkLayer w={w} h={h}>
        {scene.items.map((item, i) => {
          const cy = top + rowH * i + rowH / 2;
          const c = i === 0 ? color : INK_DIM;
          const grow = easeOut(ramp(t, at(i) + 200, 650));
          const len = Math.max(6 * k, ((item.value ?? 0) / max) * barMax);
          const [fill, edge] = sketch.hatched(barX, cy - rowH * 0.2, len, rowH * 0.4, seed + 20 + i, 12 * k);
          return (
            <g key={i}>
              <Stroke d={sketch.ellipse(badge / 2 + 4 * k, cy, badge, badge, seed + i * 3, { roughness: 1.2 })} p={easeOut(ramp(t, at(i), 450))} color={c} width={4.5 * k} />
              {withValues && grow > 0 && (
                <g opacity={grow}>
                  <clipPath id={`${id}-rank${i}`}>
                    <rect x={barX - 6 * k} y={cy - rowH / 2} width={len * grow + 12 * k} height={rowH} />
                  </clipPath>
                  <g clipPath={`url(#${id}-rank${i})`}>
                    <path d={fill} fill="none" stroke={i === 0 ? color : INK} strokeWidth={3 * k} strokeLinecap="round" opacity={0.75} />
                    <path d={edge} fill="none" stroke={i === 0 ? color : INK} strokeWidth={3.5 * k} strokeLinecap="round" strokeLinejoin="round" />
                  </g>
                </g>
              )}
            </g>
          );
        })}
      </InkLayer>
      {scene.items.map((item, i) => {
        const cy = top + rowH * i + rowH / 2;
        const p = easeOut(ramp(t, at(i), 400));
        const grow = easeOut(ramp(t, at(i) + 200, 650));
        const len = Math.max(6 * k, ((item.value ?? 0) / max) * barMax);
        return (
          <div key={i} style={{ opacity: p }}>
            <div style={{ position: 'absolute', left: 4 * k, width: badge, top: cy - badge / 2, height: badge, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: badge * 0.5, color: i === 0 ? color : INK, transform: `scale(${0.6 + 0.4 * backOut(ramp(t, at(i), 380))})` }}>{i + 1}</div>
            <div style={{ position: 'absolute', left: labelLeft, width: barX - labelLeft - 20 * k, top: cy - fs * 0.62, fontFamily: i === 0 ? DISPLAY_FONT : FONT, fontWeight: 800, fontSize: fs, lineHeight: 1.2, color: i === 0 ? color : INK, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', transform: `translateX(${(1 - p) * -24 * k}px)` }}>{item.label}</div>
            {withValues && (
              <div style={{ position: 'absolute', left: barX + len * grow + 14 * k, top: cy - 20 * k, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: 32 * k, lineHeight: 1.25, color: i === 0 ? color : INK, whiteSpace: 'nowrap', opacity: grow > 0 ? 1 : 0 }}>
                {value((item.value ?? 0) * grow, item.value)}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
};

/** Dictionary card: the term is typed out and underlined, the meaning inks in word by word. */
export const DefinitionView = ({ scene, ctx }: { scene: DefinitionScene; ctx: SceneCtx }) => {
  const { t, w, h, k, color, id } = ctx;
  const seed = seedOf(id);
  const pad = 46 * k;
  const termFs = fitFont(scene.term, w * 0.72, 1, 92 * k, 44 * k);
  const typing = Math.min(900, scene.term.length * 60);
  const typed = Math.ceil(ramp(t, 200, typing) * scene.term.length);
  const termW = Math.min(w - pad * 2 - 90 * k, scene.term.length * termFs * 0.56);
  const underY = pad + termFs * 1.12;
  const kindY = underY + 18 * k;
  const ruleY = kindY + (scene.kind ? 54 * k : 10 * k);
  const words = scene.text.split(/\s+/);
  const textAt = 200 + typing + 300;
  const shown = Math.ceil(easeOut(ramp(t, textAt, Math.min(2200, words.length * 100))) * words.length);
  const textFs = fitFont(scene.text, w - pad * 2, 3, 46 * k, 28 * k);
  const sourceAt = textAt + Math.min(2200, words.length * 100) + 200;
  return (
    <>
      <InkLayer w={w} h={h}>
        <Stroke d={sketch.rect(6 * k, 6 * k, w - 12 * k, h - 12 * k, seed, { roughness: 1.1 })} p={easeOut(ramp(t, 0, 700))} color={INK_DIM} width={3 * k} />
        <Stroke d={sketch.line([pad - 6 * k, underY], [pad + termW + 10 * k, underY + 5 * k], seed + 1, { roughness: 1.5, bowing: 1.5 })} p={easeOut(ramp(t, 200 + typing, 450))} color={color} width={7 * k} />
        <Stroke d={sketch.line([pad, ruleY], [w - pad, ruleY], seed + 2, { roughness: 0.9 })} p={easeOut(ramp(t, textAt - 200, 500))} color={INK_DIM} width={2.5 * k} opacity={0.7} />
      </InkLayer>
      <div style={{ position: 'absolute', right: pad - 8 * k, top: pad - 6 * k }}>
        <DrawnIcon name="book" size={64 * k} color={INK_DIM} p={easeInOut(ramp(t, 100, 900))} strokeWidth={1.6} />
      </div>
      <div style={{ position: 'absolute', left: pad, top: pad - termFs * 0.08, maxWidth: w - pad * 2 - 90 * k, fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: termFs, lineHeight: 1.1, color, whiteSpace: 'nowrap', overflow: 'hidden' }}>
        <span>{scene.term.slice(0, typed)}</span>
        <span style={{ opacity: 0 }}>{scene.term.slice(typed)}</span>
      </div>
      {scene.kind && (
        <Reveal p={easeOut(ramp(t, 200 + typing, 400))} dy={0} style={{ position: 'absolute', left: pad, top: kindY, fontFamily: FONT, fontStyle: 'italic', fontWeight: 600, fontSize: 30 * k, color: INK_DIM }}>
          {scene.kind}
        </Reveal>
      )}
      <div style={{ position: 'absolute', left: pad, right: pad, top: ruleY + 26 * k, bottom: scene.source ? 64 * k : pad, fontFamily: FONT, fontWeight: 600, fontSize: textFs, lineHeight: 1.3, color: INK }}>
        {words.map((word, i) => (
          <span key={i} style={{ opacity: i < shown ? 1 : 0 }}>
            {word}{' '}
          </span>
        ))}
      </div>
      {scene.source && (
        <Reveal p={easeOut(ramp(t, sourceAt, 400))} style={{ position: 'absolute', right: pad, bottom: 24 * k, fontFamily: FONT, fontWeight: 700, fontSize: 28 * k, color }}>
          — {scene.source}
        </Reveal>
      )}
    </>
  );
};

const shortModel = (model: string) => model.split('/').pop() ?? model;

/** A rap battle's score sheet: the rappers on top, the judge's scores round by round (the
 *  round's better score bright), the totals, then the winner is crowned. */
const ScoreSheetView = ({ scene, ctx }: { scene: ScoreboardScene; ctx: SceneCtx }) => {
  const { t, w, h, k, cast, id } = ctx;
  const seed = seedOf(id);
  const rounds = scene.rounds ?? [];
  const debaters = scene.speaker_ids.map((sid) => cast.find((s) => s.id === sid)).filter((s) => s !== undefined);
  const n = Math.max(1, debaters.length);
  const labelW = w * 0.24;
  const colW = (w - labelW) / n;
  const cx = (i: number) => labelW + colW * (i + 0.5);
  const headH = scene.headline ? 84 * k : 0;
  const logo = Math.min(colW * 0.3, h * 0.19, 130 * k);
  const crownH = 46 * k;
  const nameFs = Math.min(40 * k, ...debaters.map((d) => fitFont(d.name, colW - 30 * k, 1, 44 * k, 22 * k)));
  const tableTop = crownH + logo + nameFs * 1.5 + 20 * k;
  const rowH = Math.min(76 * k, (h - headH - tableTop - 8 * k) / (rounds.length + 1));
  const scoreFs = rowH * 0.56;
  const totals = debaters.map((d) => rounds.reduce((sum, r) => sum + (r.scores[d.id] ?? 0), 0));
  const rowAt = (i: number) => 600 + i * 550;
  const totalAt = rowAt(rounds.length);
  // The winner is crowned when the judge calls the result (`decide_ms`), never before the totals.
  const decideAt = Math.max(totalAt + 500, scene.decide_ms ?? 0);
  const decided = easeOut(ramp(t, decideAt, 450));
  const winnerIndex = debaters.findIndex((d) => d.id === scene.winner_id);
  const row = (i: number) => tableTop + rowH * i;
  return (
    <>
      <InkLayer w={w} h={h}>
        {[...rounds.map((_, i) => i), rounds.length].map((i) => (
          <Stroke key={i} d={sketch.line([w * 0.03, row(i)], [w * 0.97, row(i)], seed + i, { roughness: 0.6 })} p={easeOut(ramp(t, rowAt(i) - 200, 400))} color={INK_DIM} width={2 * k} />
        ))}
        {winnerIndex >= 0 && (
          <Stroke
            d={sketch.ellipse(cx(winnerIndex), row(rounds.length) + rowH / 2, scoreFs * 2.6, rowH * 1.05, seed + 9, { roughness: 1.3 })}
            p={easeOut(ramp(t, decideAt, 600))}
            color={debaters[winnerIndex].color}
            width={5 * k}
          />
        )}
      </InkLayer>
      {debaters.map((d, i) => {
        const winner = i === winnerIndex;
        const enter = ramp(t, i * 250, 450);
        const dim = winnerIndex >= 0 && !winner ? 1 - 0.5 * decided : 1;
        return (
          <div key={d.id} style={{ position: 'absolute', left: labelW + colW * i, top: 0, width: colW, height: tableTop, opacity: Math.min(1, enter * 2) * dim, transform: `translateY(${(1 - easeOut(enter)) * 24 * k}px)` }}>
            {winner && (
              <div style={{ position: 'absolute', left: (colW - crownH) / 2, top: 0 }}>
                <DrawnIcon name="crown" size={crownH} color={d.color} p={easeInOut(ramp(t, decideAt + 100, 800))} strokeWidth={1.8} fill={t > decideAt + 900 ? `${d.color}40` : undefined} />
              </div>
            )}
            <div style={{ position: 'absolute', left: (colW - logo) / 2, top: crownH }}>
              <LogoTile speaker={d} size={logo} framed={winner && decided > 0} />
            </div>
            <div style={{ position: 'absolute', left: 8 * k, right: 8 * k, top: crownH + logo + 10 * k, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: nameFs, lineHeight: 1.1, color: d.color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.name}</div>
          </div>
        );
      })}
      {rounds.map((r, i) => {
        const best = Math.max(...debaters.map((d) => r.scores[d.id] ?? 0));
        const shown = easeOut(ramp(t, rowAt(i), 400));
        return (
          <div key={r.round} style={{ opacity: shown }}>
            <div style={{ position: 'absolute', left: w * 0.03, width: labelW - w * 0.03, top: row(i), height: rowH, display: 'flex', alignItems: 'center', fontFamily: MONO_FONT, fontSize: Math.min(26 * k, rowH * 0.36), letterSpacing: 3 * k, color: INK_DIM }}>
              ROUND {r.round}
            </div>
            {debaters.map((d, j) => {
              const score = r.scores[d.id];
              return (
                <div key={d.id} style={{ position: 'absolute', left: labelW + colW * j, width: colW, top: row(i), height: rowH, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: scoreFs, color: d.color, opacity: score === best ? 1 : 0.45, transform: `scale(${0.7 + 0.3 * backOut(ramp(t, rowAt(i) + j * 120, 380))})` }}>
                  {score ?? '–'}
                </div>
              );
            })}
          </div>
        );
      })}
      <div style={{ opacity: easeOut(ramp(t, totalAt, 400)) }}>
        <div style={{ position: 'absolute', left: w * 0.03, width: labelW - w * 0.03, top: row(rounds.length), height: rowH, display: 'flex', alignItems: 'center', fontFamily: FONT, fontWeight: 900, fontSize: Math.min(30 * k, rowH * 0.42), letterSpacing: 3 * k, color: INK }}>
          TOTAL
        </div>
        {debaters.map((d, j) => (
          <div key={d.id} style={{ position: 'absolute', left: labelW + colW * j, width: colW, top: row(rounds.length), height: rowH, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: DISPLAY_FONT, fontWeight: 900, fontSize: scoreFs * 1.15, color: d.color }}>
            {totals[j]}
          </div>
        ))}
      </div>
      {scene.headline && (
        <Reveal p={easeOut(ramp(t, decideAt + 400, 450))} style={{ position: 'absolute', left: w * 0.04, right: w * 0.04, bottom: 0, height: headH, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', fontFamily: FONT, fontWeight: 700, fontSize: fitFont(scene.headline, w * 0.9, 2, 34 * k, 22 * k), lineHeight: 1.2, color: INK }}>
          {scene.headline}
        </Reveal>
      )}
    </>
  );
};

/** The judge's result: the debaters line up, then the winner is crowned (or a draw stamped).
 *  With the judge's round scores (rap battles) it is the score sheet. */
export const ScoreboardView = ({ scene, ctx }: { scene: ScoreboardScene; ctx: SceneCtx }) => {
  if (scene.rounds?.length) return <ScoreSheetView scene={scene} ctx={ctx} />;
  const { t, w, h, k, cast, id } = ctx;
  const seed = seedOf(id);
  const debaters = scene.speaker_ids.map((sid) => cast.find((s) => s.id === sid)).filter((s) => s !== undefined);
  const n = Math.max(1, debaters.length);
  const colW = w / n;
  const headH = scene.headline ? 100 * k : 0;
  const size = Math.min(colW * 0.42, (h - headH) * 0.36, 210 * k);
  const crownH = 64 * k;
  const logoTop = crownH + 14 * k;
  const nameTop = logoTop + size + 18 * k;
  const nameFs = Math.min(48 * k, ...debaters.map((d) => fitFont(d.name, colW - 30 * k, 1, 52 * k, 26 * k)));
  const revealAt = 700 + n * 250;
  const decided = easeOut(ramp(t, revealAt, 450));
  const draw = !scene.winner_id;
  const stamp = backOut(ramp(t, revealAt + 250, 420));
  return (
    <>
      <InkLayer w={w} h={h}>
        {debaters.map((d, i) =>
          d.id === scene.winner_id ? <Stroke key={d.id} d={sketch.ellipse(colW * (i + 0.5), logoTop + size / 2, size * 1.35, size * 1.3, seed + i, { roughness: 1.3 })} p={easeOut(ramp(t, revealAt, 600))} color={d.color} width={5 * k} /> : null,
        )}
      </InkLayer>
      {debaters.map((d, i) => {
        const x = colW * i;
        const winner = d.id === scene.winner_id;
        const enter = ramp(t, i * 250, 450);
        const dim = !draw && !winner ? 1 - 0.55 * decided : 1;
        return (
          <div key={d.id} style={{ position: 'absolute', left: x, top: 0, width: colW, height: h - headH, opacity: Math.min(1, enter * 2) * dim, transform: `translateY(${(1 - easeOut(enter)) * 30 * k}px) scale(${winner ? 1 + 0.06 * decided : 1})`, transformOrigin: '50% 40%' }}>
            {winner && (
              <div style={{ position: 'absolute', left: (colW - crownH) / 2, top: 0 }}>
                <DrawnIcon name="crown" size={crownH} color={d.color} p={easeInOut(ramp(t, revealAt + 100, 800))} strokeWidth={1.8} fill={t > revealAt + 900 ? `${d.color}40` : undefined} />
              </div>
            )}
            <div style={{ position: 'absolute', left: (colW - size) / 2, top: logoTop }}>
              <LogoTile speaker={d} size={size} framed={winner && decided > 0} />
            </div>
            <div style={{ position: 'absolute', left: 10 * k, right: 10 * k, top: nameTop, textAlign: 'center', fontFamily: DISPLAY_FONT, fontWeight: 800, fontSize: nameFs, lineHeight: 1.1, color: d.color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.name}</div>
            <div style={{ position: 'absolute', left: 10 * k, right: 10 * k, top: nameTop + nameFs * 1.2, textAlign: 'center', fontFamily: MONO_FONT, fontSize: 19 * k, color: INK_DIM, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{shortModel(d.model)}</div>
            {winner && stamp > 0 && (
              <div style={{ position: 'absolute', left: 0, right: 0, top: nameTop + nameFs * 1.2 + 40 * k, display: 'flex', justifyContent: 'center' }}>
                <div style={{ padding: `${6 * k}px ${22 * k}px`, border: `${4 * k}px solid ${d.color}`, borderRadius: 12 * k, fontFamily: FONT, fontWeight: 900, fontSize: 30 * k, letterSpacing: 5 * k, color: d.color, opacity: Math.min(1, stamp * 2), transform: `rotate(-6deg) scale(${2 - stamp})` }}>WINNER</div>
              </div>
            )}
          </div>
        );
      })}
      {draw && stamp > 0 && (
        <div style={{ position: 'absolute', left: 0, right: 0, top: logoTop + size * 0.35, display: 'flex', justifyContent: 'center' }}>
          <div style={{ padding: `${8 * k}px ${30 * k}px`, border: `${5 * k}px solid ${INK}`, borderRadius: 14 * k, background: '#0c1226e6', fontFamily: FONT, fontWeight: 900, fontSize: 52 * k, letterSpacing: 8 * k, color: INK, opacity: Math.min(1, stamp * 2), transform: `rotate(-5deg) scale(${2 - stamp})` }}>DRAW</div>
        </div>
      )}
      {scene.headline && (
        <Reveal p={easeOut(ramp(t, revealAt + 600, 450))} style={{ position: 'absolute', left: w * 0.04, right: w * 0.04, bottom: 0, height: headH, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', fontFamily: FONT, fontWeight: 700, fontSize: fitFont(scene.headline, w * 0.9, 2, 36 * k, 24 * k), lineHeight: 1.2, color: INK }}>
          {scene.headline}
        </Reveal>
      )}
    </>
  );
};
