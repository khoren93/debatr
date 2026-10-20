import type { CSSProperties, ReactNode } from 'react';
import type { Participant } from '../../api/types';
import { debaterColor } from '../../lib/format';
import { modelAuthor, modelIcon } from '../../lib/modelIcons';
import { debaterNames } from './helpers';

/** Horizontal lean of every seam between two sides, in % of the width (top vs bottom). */
const LEAN = 3.5;

interface CoverLayout {
  aspect: string;
  /** Height of the logo centres, in % of the cover height. */
  logoY: number;
  /** Logo width in % of the cover width by number of sides. */
  logo: Record<number, number>;
  /** VS mark diameter and name size in % of the width: [two sides, three or four]. */
  vs: [number, number];
  name: [number, number];
  /** Smallest name size in px (the poster also runs at phone width). */
  nameMin?: number;
  /** Space between a logo and its name, in % of the width. */
  gap: number;
  /** Padding of the top-corner overlays. */
  corners: string;
  /** Shade at the bottom (the poster's question sits on it). */
  shade: string;
  vsClass?: string;
}

const LAYOUTS = {
  /** Gallery / library cards: 16:9 like the AI covers they sit next to (CardCover). */
  card: { aspect: 'aspect-video', logoY: 50, logo: { 2: 17, 3: 13, 4: 10.5 }, vs: [9, 7.2], name: [3.2, 2.4], gap: 2.2, corners: 'p-3', shade: 'h-1/3 from-black/45' },
  /** The long video's first frame (`video/components/FaceOff` in the intro card): logos as high
   *  as there (the player's button sits below the VS), room for the question, a pulsing VS mark. */
  poster: { aspect: 'aspect-video', logoY: 31, logo: { 2: 13, 3: 9.4, 4: 7.3 }, vs: [7.2, 5.6], name: [1.7, 1.4], nameMin: 9, gap: 2.2, corners: 'px-[2.4cqw] py-[2.2cqw]', shade: 'h-3/5 from-ink/90', vsClass: 'motion-safe:animate-vs-pulse' },
} satisfies Record<string, CoverLayout>;

const sideClip = (i: number, n: number) => {
  const left = (i / n) * 100;
  const right = ((i + 1) / n) * 100;
  const lt = i === 0 ? 0 : left + LEAN;
  const lb = i === 0 ? 0 : left - LEAN;
  const rt = i === n - 1 ? 100 : right + LEAN;
  const rb = i === n - 1 ? 100 : right - LEAN;
  return `polygon(${lt}% 0, ${rt}% 0, ${rb}% 100%, ${lb}% 100%)`;
};

/** A provider logo sized in container units (the cover scales with its card). `eager` above the
 *  fold (the poster), lazy in card grids. */
const BigLogo = ({ modelId, color, size, eager }: { modelId: string; color: string; size: number; eager: boolean }) => {
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
  return <img src={icon.src} alt="" loading={eager ? 'eager' : 'lazy'} decoding="async" className="block" style={box} />;
};

interface DebateCoverProps {
  participants: Participant[];
  /** `card` = gallery cover (title below it), `poster` = the video's first frame (room for the
   *  question); both 16:9. */
  layout?: keyof typeof LAYOUTS;
  /** Overlays in the top corners (badges). */
  topLeft?: ReactNode;
  topRight?: ReactNode;
  /** Drawn over everything else (sized in `cqw` of the cover). */
  children?: ReactNode;
}

/**
 * Face-off cover for gallery cards: every debater's provider logo, big, on a half in its
 * speaker colour, the halves split by slanted seams with a VS mark. Pure markup — nothing to
 * generate, works for old debates, and never gives the winner away (blind voting).
 */
export const DebateCover = ({ participants, layout = 'card', topLeft, topRight, children }: DebateCoverProps) => {
  const look: CoverLayout = LAYOUTS[layout];
  const debaters = participants.filter((p) => p.role !== 'moderator').slice(0, 4);
  const names = debaterNames(participants);
  const sides = debaters.length >= 2 ? debaters : [...debaters, ...Array.from({ length: 2 - debaters.length }, () => null)];
  const n = sides.length;
  const logo = look.logo[n] ?? look.logo[4];
  const vs = n > 2 ? look.vs[1] : look.vs[0];

  return (
    <div className={`relative overflow-hidden bg-ink ${look.aspect}`} style={{ containerType: 'inline-size' }}>
      {sides.map((_, i) => {
        const color = debaterColor(i);
        const cx = ((i + 0.5) / n) * 100;
        return (
          <div
            key={i}
            className="absolute inset-0"
            style={{
              clipPath: sideClip(i, n),
              background: `radial-gradient(circle at ${cx}% ${look.logoY}%, ${color}66 0%, ${color}1f 38%, transparent 70%), linear-gradient(180deg, ${color}26, ${color}0d)`,
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
      <div className={`absolute inset-x-0 bottom-0 bg-linear-to-t to-transparent ${look.shade}`} />

      {sides.map((p, i) => {
        const color = debaterColor(i);
        const cx = ((i + 0.5) / n) * 100;
        const name = n > 2 ? look.name[1] : look.name[0];
        return (
          <div key={i} className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center" style={{ left: `${cx}%`, top: `${look.logoY}%`, width: `${100 / n - 4}%` }}>
            <span className="transition-transform duration-300 group-hover:scale-[1.06]">{p ? <BigLogo modelId={p.model} color={color} size={logo} eager={layout === 'poster'} /> : <span className="block rounded-full bg-white/10" style={{ width: `${logo}cqw`, height: `${logo}cqw` }} />}</span>
            <span className="max-w-full truncate font-mono font-semibold uppercase" style={{ color, marginTop: `${look.gap}cqw`, fontSize: look.nameMin ? `max(${look.nameMin}px, ${name}cqw)` : `${name}cqw`, letterSpacing: n > 2 ? '0.03em' : '0.12em' }}>
              {p ? names[i] : '—'}
            </span>
          </div>
        );
      })}

      {sides.slice(1).map((_, k) => (
        <span
          key={k}
          className={`absolute grid -translate-x-1/2 -translate-y-1/2 -rotate-[8deg] place-items-center rounded-full border-accent bg-ink font-display font-extrabold text-accent ${look.vsClass ?? ''}`}
          style={{ left: `${((k + 1) / n) * 100 + LEAN * (1 - (2 * look.logoY) / 100)}%`, top: `${look.logoY}%`, width: `${vs}cqw`, height: `${vs}cqw`, fontSize: `${vs * 0.4}cqw`, borderWidth: `${vs * 0.044}cqw`, boxShadow: `0 0 ${vs / 2}cqw rgba(217,255,61,0.35)` }}
        >
          VS
        </span>
      ))}

      {(topLeft || topRight) && (
        <div className={`absolute inset-x-0 top-0 flex items-center justify-between gap-2 ${look.corners}`}>
          <div className="min-w-0 flex-1">{topLeft}</div>
          {topRight && <div className="shrink-0">{topRight}</div>}
        </div>
      )}
      {children}
    </div>
  );
};
