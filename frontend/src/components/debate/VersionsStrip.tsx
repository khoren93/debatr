import { Link } from 'react-router';
import { Eye, Heart, Layers, Plus } from 'lucide-react';
import type { MotionDetail, MotionVersion, Participant } from '../../api/types';
import { formatCount, shortModelName } from '../../lib/format';
import { ModelIcon } from '../ui';

interface VersionsStripProps {
  motion: MotionDetail;
  /** The viewed debate's language: other versions name theirs when it differs. */
  languageCode: string;
  /** Debate the "Add your version" remix starts from. */
  remixId: string;
}

const CHIP = 'grid w-[210px] shrink-0 gap-1.5 rounded-[14px] border px-3 py-2.5 transition-colors';

/** Versions differ by their models: a Free Router debater is named after the model it pinned
 *  ("Free Router A" says nothing here), everyone else by their stage name. */
const lineupOf = (participants: Participant[]) =>
  participants
    .filter((p) => p.role !== 'moderator')
    .map((p) => (p.router ? shortModelName(p.model) : p.name?.trim() || shortModelName(p.model)))
    .join(' vs ');

const VersionChip = ({ version, languageCode }: { version: MotionVersion; languageCode: string }) => {
  const debaters = version.participants.filter((p) => p.role !== 'moderator');
  const body = (
    <>
      <div className="flex min-w-0 items-center gap-1.5">
        {debaters.slice(0, 4).map((p, i) => (
          <ModelIcon key={`${p.model}-${i}`} modelId={p.model} size={16} />
        ))}
        {version.language_code !== languageCode && <span className="ml-auto rounded bg-surface-3 px-1.5 py-px font-mono text-[10px] uppercase text-text-3">{version.language_code}</span>}
      </div>
      <div className="truncate text-[13px] font-semibold text-text-2" title={lineupOf(version.participants)}>
        {lineupOf(version.participants)}
      </div>
      <div className="flex items-center gap-2.5 font-mono text-[10px] text-dim">
        {version.current ? (
          <span className="tracking-[0.08em] text-accent">WATCHING</span>
        ) : (
          <>
            <span className="inline-flex items-center gap-1" title={`${version.likes} likes`}>
              <Heart className="size-3" /> {formatCount(version.likes)}
            </span>
            <span className="inline-flex items-center gap-1" title={`${version.views} views`}>
              <Eye className="size-3" /> {formatCount(version.views)}
            </span>
          </>
        )}
      </div>
    </>
  );
  if (version.current) {
    return (
      <div className={`${CHIP} border-accent/50 bg-accent/5`} aria-current="page">
        {body}
      </div>
    );
  }
  return (
    <Link to={version.path || `/d/${version.slug}`} title={version.topic} className={`${CHIP} border-line bg-surface hover:border-line-3`}>
      {body}
    </Link>
  );
};

/**
 * The other published versions of this debate's topic: the same question argued by other models
 * (or in another language). No winners here: the audience votes blind.
 */
export const VersionsStrip = ({ motion, languageCode, remixId }: VersionsStripProps) => {
  if (!motion.items.some((v) => !v.current)) return null;
  const published = motion.items.some((v) => v.current);
  const n = motion.versions;
  // The version being watched leads; the others follow most liked first.
  const items = [...motion.items].sort((a, b) => Number(b.current) - Number(a.current));
  const heading = published ? `${n} versions of this topic` : `${n} published ${n === 1 ? 'version' : 'versions'} of this topic`;
  return (
    <section className="grid min-w-0 gap-2.5" aria-label="Versions of this topic">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="inline-flex items-center gap-2 font-display text-[17px] font-bold tracking-[-0.02em]">
          <Layers className="size-4 text-accent" /> {heading}
        </h2>
        <div className="flex items-center gap-4 text-sm">
          <Link to={`/create?remix=${remixId}`} className="inline-flex items-center gap-1 text-accent transition-colors hover:text-accent-hover">
            <Plus className="size-4" /> Add your version
          </Link>
          <Link to={motion.path || `/t/${motion.slug}`} className="text-muted transition-colors hover:text-text">
            {n > motion.items.length ? `All ${n} →` : 'Topic page →'}
          </Link>
        </div>
      </div>
      <div className="-mx-1 flex gap-2.5 overflow-x-auto px-1 pb-1 [scrollbar-width:thin]">
        {items.map((v) => (
          <VersionChip key={v.id} version={v} languageCode={languageCode} />
        ))}
      </div>
    </section>
  );
};
