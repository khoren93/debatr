import { APP_NAME } from '../../lib/brand';

/** The mark: the D of Debatr as a speech bubble with a voice wave, on an accent tile (= public/favicon.svg). */
export const LogoMark = ({ size = 30 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" className="shrink-0">
    <rect width="64" height="64" rx="18" className="fill-accent" />
    <path d="M14 18a6 6 0 0 1 6-6h11a19 19 0 0 1 0 38h-7l-10 8.5V18Z" className="fill-ink" />
    <g className="fill-accent">
      <rect x="20.9" y="26" width="5" height="10" rx="2.5" />
      <rect x="28.5" y="21" width="5" height="20" rx="2.5" />
      <rect x="36.1" y="24.5" width="5" height="13" rx="2.5" />
    </g>
  </svg>
);

/** Mark + wordmark. */
export const Logo = ({ size = 30, wordmark = true }: { size?: number; wordmark?: boolean }) => (
  <span className="inline-flex items-center gap-2.5">
    <LogoMark size={size} />
    {wordmark && <span className="font-display text-lg font-bold tracking-tight">{APP_NAME}</span>}
  </span>
);

/** Animated equalizer bars (live / rendering indicators). */
export const Bars = ({ color = '#D9FF3D', height = 22 }: { color?: string; height?: number }) => (
  <span className="flex items-end gap-[3px]" style={{ height }}>
    {[0, 0.15, 0.3, 0.45].map((delay) => (
      <span key={delay} className="w-[3px] origin-bottom animate-bars" style={{ background: color, height: '100%', animationDelay: `${delay}s` }} />
    ))}
  </span>
);
