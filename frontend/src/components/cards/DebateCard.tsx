import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router';
import { AudioLines, Clock, Eye, Heart, Layers, MicVocal } from 'lucide-react';
import type { MotionRef, Participant, Verdict } from '../../api/types';
import { formatCount, formatDuration, gradientFor } from '../../lib/format';
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
  /** Picture in place of the gradient thumbnail (e.g. DebateCover); the title then sits below it. */
  cover?: ReactNode;
  footerLeft?: ReactNode;
  footerRight?: ReactNode;
  /** Position in the grid — staggers the rise animation. */
  index?: number;
  className?: string;
  style?: CSSProperties;
}

/** Gradient 16:9 thumbnail card used by the landing, library and gallery grids. */
export const DebateCard = ({ id, to, title, topLeft, topRight, cover, footerLeft, footerRight, index = 0, className = '', style }: DebateCardProps) => (
  <Link
    to={to}
    className={`group block overflow-hidden rounded-card border border-line bg-surface transition-[translate,border-color] duration-200 hover:-translate-y-[3px] hover:border-line-3 animate-rise ${className}`}
    style={{ animationDelay: `${Math.min(index, 10) * 40}ms`, ...style }}
  >
    {cover ? (
      <>
        {cover}
        <div className="line-clamp-2 px-3.5 pt-3 font-display text-[16px] font-bold leading-[1.2] tracking-[-0.02em] text-balance">{title}</div>
      </>
    ) : (
      <Thumb gradient={gradientFor(id)}>
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 flex-1">{topLeft}</div>
          {topRight && <div className="shrink-0">{topRight}</div>}
        </div>
        <div className="line-clamp-3 font-display text-[17px] font-bold leading-[1.15] tracking-[-0.02em] text-balance">{title}</div>
      </Thumb>
    )}
    {(footerLeft || footerRight) && (
      <div className={`flex items-center justify-between gap-2.5 px-3.5 pb-3 text-xs text-muted ${cover ? 'pt-2' : 'pt-3'}`}>
        <div className="flex min-w-0 items-center gap-2">{footerLeft}</div>
        {footerRight && <div className="flex shrink-0 items-center gap-1.5">{footerRight}</div>}
      </div>
    )}
  </Link>
);

/** "4:13" chip for the thumbnail corner ("—" when the debate has no audio yet). */
export const DurationChip = ({ ms }: { ms: number | null | undefined }) => (
  <span className="inline-block rounded-md bg-black/45 px-2 py-[3px] font-mono text-[10px] text-text">{formatDuration(ms)}</span>
);

/** Cover badge of a debate voiced with premium (ElevenLabs) voices. */
export const PremiumVoicesBadge = () => (
  <span className="inline-flex items-center gap-1 rounded-md bg-black/55 px-2 py-[3px] font-mono text-[10px] tracking-[0.06em] text-accent backdrop-blur-sm" title="Voiced with premium voices">
    <AudioLines className="size-3" /> PREMIUM VOICES
  </span>
);

/** Cover badge of a show format other than the debate ("RAP BATTLE"); nothing for a debate. */
export const FormatBadge = ({ format }: { format: string | undefined }) =>
  format === 'rap_battle' ? (
    <span className="inline-flex items-center gap-1 rounded-md bg-black/55 px-2 py-[3px] font-mono text-[10px] tracking-[0.06em] text-accent backdrop-blur-sm" title="Rap battle: verses over one beat">
      <MicVocal className="size-3" /> RAP BATTLE
    </span>
  ) : null;

/** The cover's top-right badge: the format of a battle (always voiced with premium voices, so
 *  that badge would say nothing new), else premium voices when the debate has them. */
export const CoverBadge = ({ format, premiumVoices }: { format: string | undefined; premiumVoices: boolean }) =>
  format === 'rap_battle' ? <FormatBadge format={format} /> : premiumVoices ? <PremiumVoicesBadge /> : null;

/** Cover badge of a topic with several public versions: how many, and the logos of the models
 *  that argued it in the other versions (the cover already shows its own pair). */
export const VersionsBadge = ({ motion, participants }: { motion: MotionRef | null | undefined; participants: Participant[] }) => {
  if (!motion || motion.versions < 2) return null;
  const shown = new Set(participants.map((p) => p.model));
  const others = motion.models.filter((m) => !shown.has(m)).slice(0, 3);
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-black/55 px-2 py-[3px] font-mono text-[10px] tracking-[0.06em] text-text backdrop-blur-sm" title={`${motion.versions} versions of this topic`}>
      <Layers className="size-3 shrink-0" />
      <span className="truncate">{motion.versions} VERSIONS</span>
      {others.length > 0 && (
        <span className="flex shrink-0 items-center gap-0.5">
          {others.map((m) => (
            <ModelIcon key={m} modelId={m} size={11} />
          ))}
        </span>
      )}
    </span>
  );
};

/** Likes · views · length row of a public card (icons instead of words). */
export const CardStats = ({ likes, views, durationMs }: { likes: number; views: number; durationMs?: number | null }) => (
  <span className="inline-flex items-center gap-2.5">
    <span className="inline-flex items-center gap-1" title={`${likes} likes`}>
      <Heart className="size-3" /> {formatCount(likes)}
    </span>
    <span className="inline-flex items-center gap-1" title={`${views} views`}>
      <Eye className="size-3" /> {formatCount(views)}
    </span>
    {durationMs ? (
      <span className="inline-flex items-center gap-1" title="Length">
        <Clock className="size-3" /> {formatDuration(durationMs)}
      </span>
    ) : null}
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
