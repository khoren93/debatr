import type { CSSProperties } from 'react';
import { modelAuthor, modelIcon } from '../../lib/modelIcons';

interface Props {
  modelId: string | null | undefined;
  /** Logo size in px. */
  size?: number;
  /** Draw the logo on a rounded tile (leaderboard rows, speaker cards). */
  tile?: boolean;
  className?: string;
}

/** Provider logo of an OpenRouter model (Claude, GPT, Gemini…), or the author's initial. */
export const ModelIcon = ({ modelId, size = 14, tile = false, className = '' }: Props) => {
  const icon = modelIcon(modelId);
  const box: CSSProperties = { width: size, height: size };

  let mark;
  if (!icon) {
    const letter = (modelAuthor(modelId ?? '') || modelId || '?').charAt(0).toUpperCase();
    mark = (
      <span className="grid place-items-center rounded-[4px] bg-surface-4 font-bold leading-none text-text-3" style={{ ...box, fontSize: Math.round(size * 0.62) }}>
        {letter}
      </span>
    );
  } else if (icon.mono) {
    const mask = `url(${icon.src}) center / contain no-repeat`;
    mark = <span className="block bg-current" style={{ ...box, mask, WebkitMask: mask }} />;
  } else {
    mark = <img src={icon.src} alt="" width={size} height={size} loading="lazy" decoding="async" className="block" />;
  }

  if (!tile) {
    return (
      <span className={`inline-flex shrink-0 ${className}`} aria-hidden="true">
        {mark}
      </span>
    );
  }
  const pad = Math.round(size * 0.45);
  return (
    <span
      className={`inline-grid shrink-0 place-items-center border border-line bg-surface-3 text-text ${className}`}
      style={{ width: size + pad * 2, height: size + pad * 2, borderRadius: Math.round((size + pad * 2) * 0.28) }}
      aria-hidden="true"
    >
      {mark}
    </span>
  );
};
