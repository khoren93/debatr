import { modelAuthor, modelIcon } from '../../lib/modelIcons';

/** Provider logo of a model that scales with its box (the box sets the size, e.g. in cqw). */
export const ModelLogo = ({ model, className = '' }: { model: string | null | undefined; className?: string }) => {
  const icon = modelIcon(model);
  if (!icon) {
    const letter = (modelAuthor(model ?? '') || model || '?').charAt(0).toUpperCase();
    return (
      <svg viewBox="0 0 10 10" className={`size-[56%] ${className}`} aria-hidden="true">
        <text x="5" y="7.6" textAnchor="middle" fontSize="7.5" fontWeight="700" fill="#B4B8C6" fontFamily="DM Sans Variable, DM Sans, sans-serif">
          {letter}
        </text>
      </svg>
    );
  }
  if (icon.mono) {
    const mask = `url(${icon.src}) center / contain no-repeat`;
    return <span className={`block size-[56%] bg-current ${className}`} style={{ mask, WebkitMask: mask }} aria-hidden="true" />;
  }
  return <img src={icon.src} alt="" loading="lazy" decoding="async" className={`size-[56%] object-contain ${className}`} />;
};

interface Props {
  model: string | null | undefined;
  color: string;
  size?: number;
  /** Border opacity as a hex suffix ("" = solid speaker colour). */
  borderAlpha?: string;
  /** Tile background (default: card surface). */
  background?: string;
  className?: string;
}

/** Speaker's model logo on a dark tile framed in the speaker's colour. */
export const SpeakerTile = ({ model, color, size = 36, borderAlpha = '', background, className = '' }: Props) => (
  <span
    className={`grid shrink-0 place-items-center overflow-hidden border bg-surface text-text ${className}`}
    style={{ width: size, height: size, borderRadius: Math.round(size * 0.3), borderColor: `${color}${borderAlpha}`, background }}
    aria-hidden="true"
  >
    <ModelLogo model={model} />
  </span>
);
