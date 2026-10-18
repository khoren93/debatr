import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { AudioLines } from 'lucide-react';
import type { Participant, Verdict } from '../../api/types';
import { formatDuration, gradientFor } from '../../lib/format';
import { ModelIcon, Thumb } from '../ui';
import { debaterNames, verdictLabel } from './helpers';

interface DebateCardProps {
  /** Seed for the deterministic thumbnail gradient (the debate id). */
  id: string;
  to: string;
  title: string;
  /** Overlay in the top-left corner of the thumbnail (status pill, "Pro vs Con" line). */
  topLeft?: ReactNode;
  /** Overlay in the top-right corner of the thumbnail (duration chip). */
  topRight?: ReactNode;
  footerLeft?: ReactNode;
  footerRight?: ReactNode;
  /** Position in the grid — staggers the rise animation. */
  index?: number;
  className?: string;
  style?: CSSProperties;
}

/** Gradient 16:9 thumbnail card used by the landing, library and gallery grids. */
export const DebateCard = ({ id, to, title, topLeft, topRight, footerLeft, footerRight, index = 0, className = '', style }: DebateCardProps) => (
  <Link
    to={to}
    className={`group block overflow-hidden rounded-card border border-line bg-surface transition-[transform,border-color] duration-200 hover:-translate-y-[3px] hover:border-line-3 animate-rise ${className}`}
    style={{ animationDelay: `${Math.min(index, 10) * 40}ms`, ...style }}
  >
    <Thumb gradient={gradientFor(id)}>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">{topLeft}</div>
        {topRight && <div className="shrink-0">{topRight}</div>}
      </div>
      <div className="line-clamp-3 font-display text-[17px] font-bold leading-[1.15] tracking-[-0.02em] text-balance">{title}</div>
    </Thumb>
    {(footerLeft || footerRight) && (
      <div className="flex items-center justify-between gap-2.5 px-3.5 py-3 text-xs text-muted">
        <div className="flex min-w-0 items-center gap-2">{footerLeft}</div>
        {footerRight && <div className="flex shrink-0 items-center gap-1.5">{footerRight}</div>}
      </div>
    )}
  </Link>
);

/** "4:13" chip for the thumbnail corner ("—" when the debate has no audio yet); `premium` adds the premium-voices mark. */
export const DurationChip = ({ ms, premium = false }: { ms: number | null | undefined; premium?: boolean }) => (
  <span className="inline-flex items-center gap-1 rounded-md bg-black/45 px-2 py-[3px] font-mono text-[10px] text-text" title={premium ? 'Premium voices' : undefined}>
    {premium && <AudioLines className="size-3 text-accent" aria-label="Premium voices" />}
    {formatDuration(ms)}
  </span>
);

/** "Claude vs GPT-4o" mono line built from the first two debaters, with their model logos. */
export const VersusLine = ({ participants }: { participants: Participant[] }) => {
  const [pro = 'Pro', con = 'Con'] = debaterNames(participants);
  const [proModel, conModel] = participants.filter((p) => p.role !== 'moderator').map((p) => p.model);
  return (
    <span className="flex min-w-0 items-center gap-1.5 font-mono text-[10px] tracking-[0.1em] text-white/70" title={`${pro} vs ${con}`}>
      {proModel && <ModelIcon modelId={proModel} size={12} />}
      <span className="truncate">
        {pro} vs {con}
      </span>
      {conModel && <ModelIcon modelId={conModel} size={12} />}
    </span>
  );
};

/** "Alice wins" (accent) / "Draw" (host colour); renders nothing without a verdict. */
export const VerdictLine = ({ verdict, className = '' }: { verdict: Verdict | null | undefined; className?: string }) => {
  const label = verdictLabel(verdict);
  if (!label) return null;
  return <span className={`truncate font-semibold ${label.draw ? 'text-host' : 'text-accent'} ${className}`}>{label.text}</span>;
};
