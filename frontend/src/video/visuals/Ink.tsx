import type { CSSProperties, ReactNode } from 'react';
import { clamp01 } from './draw';
import { ICONS } from './icons';

/**
 * Drawing primitives. The web renderer serializes every <svg> into a standalone image, so all
 * colours and dash animation are SVG attributes on the element itself (no inherited CSS, no
 * `currentColor`), and text stays in HTML (web fonts do not load inside an SVG image).
 */

/** Full-size SVG layer for hand-drawn strokes, positioned over its parent box. */
export const InkLayer = ({ w, h, children }: { w: number; h: number; children: ReactNode }) => (
  <svg width={Math.max(1, w)} height={Math.max(1, h)} viewBox={`0 0 ${Math.max(1, w)} ${Math.max(1, h)}`} style={{ position: 'absolute', left: 0, top: 0, display: 'block' }}>
    {children}
  </svg>
);

/** A stroke drawn from its start to `p` (0..1) of its length. */
export const Stroke = ({ d, p, color, width = 4, opacity = 1 }: { d: string; p: number; color: string; width?: number; opacity?: number }) => {
  const progress = clamp01(p);
  if (progress <= 0 || !d) return null;
  return (
    <path
      d={d}
      fill="none"
      stroke={color}
      strokeWidth={width}
      strokeLinecap="round"
      strokeLinejoin="round"
      pathLength={1}
      strokeDasharray="1 1"
      strokeDashoffset={1 - progress}
      opacity={opacity}
    />
  );
};

const ICON_DASH = 100; // longer than any single path of a 24×24 Lucide icon

/** Pictogram drawn stroke by stroke (`p` 0..1); keeps its box while invisible. */
export const DrawnIcon = ({ name, size, color, p, strokeWidth = 1.7, fill }: { name: string | null; size: number; color: string; p: number; strokeWidth?: number; fill?: string }) => {
  const Icon = name ? ICONS[name] : undefined;
  const progress = clamp01(p);
  if (!Icon || progress <= 0) return <div style={{ width: size, height: size, flexShrink: 0 }} />;
  return (
    <Icon
      size={size}
      color={color}
      strokeWidth={strokeWidth}
      fill={fill ?? 'none'}
      strokeDasharray={`${ICON_DASH} ${ICON_DASH}`}
      strokeDashoffset={ICON_DASH * (1 - progress)}
      style={{ display: 'block', flexShrink: 0 }}
    />
  );
};

/** HTML content that fades and slides in with `p` (0..1). */
export const Reveal = ({ p, dy = 18, children, style }: { p: number; dy?: number; children: ReactNode; style?: CSSProperties }) => {
  const progress = clamp01(p);
  return <div style={{ opacity: progress, transform: `translateY(${(1 - progress) * dy}px)`, ...style }}>{children}</div>;
};
