import type { CSSProperties } from 'react';
import { APP_NAME } from '../../lib/brand';
import { modelAuthor } from '../../lib/modelIcons';
import { OG_HEIGHT as H, OG_WIDTH as W, type OgCard, type OgSide } from '../../lib/og';
import { DISPLAY, MONO, fontStack } from './fonts.server';
import { logoSource } from './logos.server';

/**
 * The preview card (JSX for Takumi, not for React DOM): the long video's first frame at 1200×630
 * — the debaters face off on slanted sides in their speaker colours, provider logos big and
 * glowing, a VS mark on every seam, the brand top-left, the format chip top-right and the question
 * at the bottom (video/components/Chrome IntroCard, cards/DebateCover). No winner, ever.
 */

const U = W / 100;
const INK = '#0A0B0F';
const ACCENT = '#D9FF3D';
const TEXT = '#F2F3F7';
/** Horizontal lean of every seam, as a share of the width (top vs bottom), as in the video. */
const LEAN = 0.05;
/** Height of the logo centres, as a share of the height. */
const LOGO_Y = 0.335;
const LOGO: Record<number, number> = { 1: 168, 2: 168, 3: 124, 4: 98 };
const VS: Record<number, number> = { 2: 88, 3: 70, 4: 64 };
const NAME: Record<number, number> = { 2: 24, 3: 20, 4: 18 };
const BAR = 52;
const RTL = /^(ar|he|fa|ur|ps|yi)/i;

/** Wide characters (CJK, Hangul, full-width forms) count about two Latin ones. */
const visualLength = (text: string) => [...text].reduce((n, ch) => n + (/[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]/u.test(ch) ? 1.8 : 1), 0);

/** Headline size in px: one line for a short question, up to three for the longest. */
export const headlineSize = (text: string): number => {
  const n = visualLength(text);
  return n <= 28 ? 74 : n <= 46 ? 66 : n <= 70 ? 58 : n <= 100 ? 51 : n <= 130 ? 45 : 41;
};

const seamX = (k: number, n: number, y: number) => (k / n) * W + LEAN * W * (1 - (2 * y) / H);

const sideClip = (i: number, n: number) => {
  const xt = (k: number) => (k === 0 ? 0 : k === n ? W : (k / n) * W + LEAN * W);
  const xb = (k: number) => (k === 0 ? 0 : k === n ? W : (k / n) * W - LEAN * W);
  return `polygon(${xt(i)}px 0px, ${xt(i + 1)}px 0px, ${xb(i + 1)}px ${H}px, ${xb(i)}px ${H}px)`;
};

const abs = (style: CSSProperties): CSSProperties => ({ position: 'absolute', display: 'flex', ...style });

/** The mark of public/favicon.svg. */
const BrandMark = ({ size }: { size: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64">
    <rect width="64" height="64" rx="18" fill={ACCENT} />
    <path d="M14 18a6 6 0 0 1 6-6h11a19 19 0 0 1 0 38h-7l-10 8.5V18Z" fill={INK} />
    <g fill={ACCENT}>
      <rect x="20.9" y="26" width="5" height="10" rx="2.5" />
      <rect x="28.5" y="21" width="5" height="20" rx="2.5" />
      <rect x="36.1" y="24.5" width="5" height="13" rx="2.5" />
    </g>
  </svg>
);

const Logo = ({ side, size }: { side: OgSide | null; size: number }) => {
  if (!side) return <div style={{ display: 'flex', width: size, height: size, borderRadius: size / 2, background: 'rgba(255,255,255,0.1)' }} />;
  const logo = logoSource(side.model);
  if (logo) return <img src={logo.src} width={size} height={size} style={{ width: size, height: size, filter: `drop-shadow(0 0 ${size / 5}px ${side.color}aa)` }} />;
  const letter = (modelAuthor(side.model) || side.model || '?').charAt(0).toUpperCase();
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size,
        height: size,
        borderRadius: size * 0.22,
        border: '2px solid rgba(255,255,255,0.2)',
        background: 'rgba(255,255,255,0.1)',
        boxShadow: `0 0 ${size / 4}px ${side.color}88`,
        fontFamily: fontStack(DISPLAY),
        fontWeight: 800,
        fontSize: size * 0.55,
        color: TEXT,
      }}
    >
      {letter}
    </div>
  );
};

export const OgCardView = ({ card, scripts = [] }: { card: OgCard; scripts?: string[] }) => {
  const sides: (OgSide | null)[] = card.sides.length >= 2 ? card.sides : [...card.sides, ...Array.from({ length: 2 - card.sides.length }, () => null)];
  const n = sides.length;
  const cy = H * LOGO_Y;
  const logo = LOGO[n] ?? LOGO[4];
  const vs = VS[n] ?? VS[4];
  const nameSize = NAME[n] ?? NAME[4];
  const headline = headlineSize(card.text);

  return (
    <div style={{ position: 'relative', display: 'flex', width: W, height: H, overflow: 'hidden', background: INK, fontFamily: fontStack(DISPLAY, scripts), color: TEXT }}>
      {sides.map((side, i) => {
        const color = side?.color ?? '#8B90A0';
        const cx = ((i + 0.5) / n) * 100;
        return (
          <div
            key={`side${i}`}
            style={abs({
              inset: 0,
              clipPath: sideClip(i, n),
              background: `radial-gradient(circle at ${cx}% ${LOGO_Y * 100}%, ${color}6b 0%, ${color}21 38%, transparent 70%), linear-gradient(180deg, ${color}29, ${color}0d)`,
            })}
          />
        );
      })}
      {/* Fine diagonal hatching: the printed-poster texture of the cover. */}
      <div style={abs({ inset: 0, opacity: 0.6, backgroundImage: 'repeating-linear-gradient(100deg, rgba(255,255,255,0.035) 0px 1px, transparent 1px 13px)' })} />
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: 'absolute', left: 0, top: 0 }}>
        {sides.slice(1).map((_, k) => (
          <line key={`seam${k}`} x1={((k + 1) / n) * W + LEAN * W} y1={0} x2={((k + 1) / n) * W - LEAN * W} y2={H} stroke="#FFFFFF" strokeOpacity={0.55} strokeWidth={2.5} />
        ))}
      </svg>
      {/* The question sits on a shade, as on the poster. */}
      <div style={abs({ left: 0, right: 0, bottom: 0, height: H * 0.62, backgroundImage: `linear-gradient(0deg, ${INK}f0 0%, ${INK}c0 45%, ${INK}00 100%)` })} />

      {sides.map((side, i) => {
        const cx = ((i + 0.5) / n) * W;
        const width = W / n - 4 * U;
        return (
          <div key={`face${i}`} style={abs({ left: cx - width / 2, top: cy - logo / 2, width, flexDirection: 'column', alignItems: 'center' })}>
            <Logo side={side} size={logo} />
            <div
              style={{
                display: 'block',
                marginTop: n > 2 ? 18 : 24,
                maxWidth: width,
                overflow: 'hidden',
                whiteSpace: 'nowrap',
                textOverflow: 'ellipsis',
                fontFamily: fontStack(MONO),
                fontWeight: 600,
                fontSize: nameSize,
                letterSpacing: n > 2 ? '0.04em' : '0.12em',
                textTransform: 'uppercase',
                color: side?.color ?? '#8B90A0',
              }}
            >
              {side ? side.name : '—'}
            </div>
          </div>
        );
      })}

      {sides.slice(1).map((_, k) => (
        <div
          key={`vs${k}`}
          style={abs({
            left: seamX(k + 1, n, cy) - vs / 2,
            top: cy - vs / 2,
            width: vs,
            height: vs,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: vs / 2,
            border: `${Math.max(3, vs * 0.045)}px solid ${ACCENT}`,
            background: INK,
            boxShadow: `0 0 ${vs / 2}px rgba(217,255,61,0.35)`,
            transform: 'rotate(-8deg)',
            fontFamily: fontStack(DISPLAY),
            fontWeight: 800,
            fontSize: vs * 0.4,
            lineHeight: 1,
            color: ACCENT,
          })}
        >
          VS
        </div>
      ))}

      <div style={abs({ top: 2.2 * U, left: 2.4 * U, right: 2.4 * U, height: BAR, alignItems: 'center', justifyContent: 'space-between' })}>
        <div style={{ display: 'flex', alignItems: 'center', gap: BAR * 0.3 }}>
          <BrandMark size={BAR} />
          <div style={{ display: 'flex', fontFamily: fontStack(DISPLAY), fontWeight: 700, fontSize: BAR * 0.54, letterSpacing: '-0.025em', lineHeight: 1, color: TEXT }}>{APP_NAME}</div>
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            height: BAR - 6,
            padding: '0 20px',
            borderRadius: 999,
            border: '2px solid rgba(255,255,255,0.14)',
            background: 'rgba(10,11,15,0.7)',
            fontFamily: fontStack(MONO),
            fontWeight: 500,
            fontSize: 18,
            letterSpacing: '0.1em',
            color: ACCENT,
          }}
        >
          {card.badge}
        </div>
      </div>

      <div
        lang={card.lang}
        style={abs({
          left: 6.5 * U,
          right: 6.5 * U,
          bottom: 4.6 * U,
          justifyContent: 'center',
          textAlign: 'center',
          textWrap: 'balance',
          direction: RTL.test(card.lang) ? 'rtl' : 'ltr',
          fontWeight: 800,
          fontSize: headline,
          lineHeight: 1.08,
          letterSpacing: '-0.03em',
          color: TEXT,
        })}
      >
        {card.text}
      </div>
    </div>
  );
};

/** Image sources of the card's logos (Takumi takes the bytes by `src`). */
export const cardLogos = (card: OgCard) => {
  const seen = new Map<string, Uint8Array>();
  for (const side of card.sides) {
    const logo = logoSource(side.model);
    if (logo) seen.set(logo.src, logo.data);
  }
  return [...seen].map(([src, data]) => ({ src, data }));
};
