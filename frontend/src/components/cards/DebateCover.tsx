import type { CSSProperties, ReactNode } from 'react';
import type { Participant } from '../../api/types';
import { debaterColor } from '../../lib/format';
import { modelAuthor, modelIcon } from '../../lib/modelIcons';
import { debaterNames } from './helpers';

/** Horizontal lean of every seam between two sides, in % of the width (top vs bottom). */
const LEAN = 5;
/** Logo width in % of the card width by number of sides. */
const LOGO_CQW: Record<number, number> = { 2: 21, 3: 15, 4: 11.5 };
/** Height of the logo centres, in % of the cover height. */
const LOGO_Y = 43;

const sideClip = (i: number, n: number) => {
  const left = (i / n) * 100;
  const right = ((i + 1) / n) * 100;
  const lt = i === 0 ? 0 : left + LEAN;
  const lb = i === 0 ? 0 : left - LEAN;
  const rt = i === n - 1 ? 100 : right + LEAN;
  const rb = i === n - 1 ? 100 : right - LEAN;
  return `polygon(${lt}% 0, ${rt}% 0, ${rb}% 100%, ${lb}% 100%)`;
};

/** A provider logo sized in container units (the cover scales with its card). */
const BigLogo = ({ modelId, color, size }: { modelId: string; color: string; size: number }) => {
  const icon = modelIcon(modelId);
  const box: CSSProperties = { width: `${size}cqw`, height: `${size}cqw`, filter: `drop-shadow(0 0 ${size / 5}cqw ${color}aa)` };
  if (!icon) {
    const letter = (modelAuthor(modelId) || modelId || '?').charAt(0).toUpperCase();
    return (
      <span className="grid place-items-center rounded-[22%] border border-white/20 bg-white/10 font-display font-extrabold text-white" style={{ ...box, fontSize: `${size * 0.55}cqw` }}>
        {letter}
      </span>
    );
  }
  if (icon.mono) {
    const mask = `url(${icon.src}) center / contain no-repeat`;
    return <span className="block bg-white" style={{ ...box, mask, WebkitMask: mask }} />;
  }
  return <img src={icon.src} alt="" loading="lazy" decoding="async" className="block" style={box} />;
};

interface DebateCoverProps {
  participants: Participant[];
  /** Overlays in the top corners (badges). */
  topLeft?: ReactNode;
  topRight?: ReactNode;
}

/**
 * Face-off cover for gallery cards: every debater's provider logo, big, on a half in its
 * speaker colour, the halves split by slanted seams with a VS mark. Pure markup — nothing to
 * generate, works for old debates, and never gives the winner away (blind voting).
 */
export const DebateCover = ({ participants, topLeft, topRight }: DebateCoverProps) => {
  const debaters = participants.filter((p) => p.role !== 'moderator').slice(0, 4);
  const names = debaterNames(participants);
  const sides = debaters.length >= 2 ? debaters : [...debaters, ...Array.from({ length: 2 - debaters.length }, () => null)];
  const n = sides.length;
  const logo = LOGO_CQW[n] ?? 11;

  return (
    <div className="relative aspect-video overflow-hidden bg-ink" style={{ containerType: 'inline-size' }}>
      {sides.map((_, i) => {
        const color = debaterColor(i);
        const cx = ((i + 0.5) / n) * 100;
        return (
          <div
            key={i}
            className="absolute inset-0"
            style={{
              clipPath: sideClip(i, n),
              background: `radial-gradient(circle at ${cx}% ${LOGO_Y}%, ${color}66 0%, ${color}1f 38%, transparent 70%), linear-gradient(180deg, ${color}26, ${color}0d)`,
            }}
          />
        );
      })}
      {/* Fine diagonal hatching gives the flat halves a printed-poster texture. */}
      <div className="absolute inset-0 opacity-60" style={{ background: 'repeating-linear-gradient(100deg, rgba(255,255,255,0.035) 0 1px, transparent 1px 1.1cqw)' }} />
      <svg className="absolute inset-0 size-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {sides.slice(1).map((_, k) => {
          const x = ((k + 1) / n) * 100;
          return <line key={k} x1={x + LEAN} y1={0} x2={x - LEAN} y2={100} stroke="rgba(255,255,255,0.55)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />;
        })}
      </svg>
      <div className="absolute inset-x-0 bottom-0 h-1/3 bg-linear-to-t from-black/45 to-transparent" />

      {sides.map((p, i) => {
        const color = debaterColor(i);
        const cx = ((i + 0.5) / n) * 100;
        return (
          <div key={i} className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center" style={{ left: `${cx}%`, top: `${LOGO_Y}%`, width: `${100 / n - 4}%` }}>
            <span className="transition-transform duration-300 group-hover:scale-[1.06]">{p ? <BigLogo modelId={p.model} color={color} size={logo} /> : <span className="block rounded-full bg-white/10" style={{ width: `${logo}cqw`, height: `${logo}cqw` }} />}</span>
            <span className="mt-[2.4cqw] max-w-full truncate font-mono font-semibold uppercase" style={{ color, fontSize: `${n > 2 ? 2.1 : 2.8}cqw`, letterSpacing: n > 2 ? '0.03em' : '0.12em' }}>
              {p ? names[i] : '—'}
            </span>
          </div>
        );
      })}

      {sides.slice(1).map((_, k) => (
        <span
          key={k}
          className="absolute grid -translate-x-1/2 -translate-y-1/2 -rotate-[8deg] place-items-center rounded-full border-accent bg-ink font-display font-extrabold text-accent"
          style={{ left: `${((k + 1) / n) * 100 + LEAN * (1 - (2 * LOGO_Y) / 100)}%`, top: `${LOGO_Y}%`, width: `${n > 2 ? 7.5 : 9.5}cqw`, height: `${n > 2 ? 7.5 : 9.5}cqw`, fontSize: `${n > 2 ? 3 : 3.8}cqw`, borderWidth: '0.35cqw', boxShadow: '0 0 4cqw rgba(217,255,61,0.35)' }}
        >
          VS
        </span>
      ))}

      {(topLeft || topRight) && (
        <div className="absolute inset-x-0 top-0 flex items-center justify-between gap-2 p-3">
          <div className="min-w-0 flex-1">{topLeft}</div>
          {topRight && <div className="shrink-0">{topRight}</div>}
        </div>
      )}
    </div>
  );
};
