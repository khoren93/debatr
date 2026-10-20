import type { ReactNode } from 'react';
import type { CoverImage, Participant } from '../../api/types';
import { DebateCover } from './DebateCover';

interface CardCoverProps {
  /** The debate's AI cover; null: the markup cover. */
  cover: CoverImage | null | undefined;
  participants: Participant[];
  topLeft?: ReactNode;
  topRight?: ReactNode;
}

/**
 * A card's cover: the AI cover where the debate has one (backend services/media/cover.py),
 * else the markup face-off; both 16:9. An AI cover carries its own format badge (top-left), so
 * the site's badges stack in its top-right corner, which its prompt keeps free of text.
 */
export const CardCover = ({ cover, participants, topLeft, topRight }: CardCoverProps) => {
  if (!cover) return <DebateCover participants={participants} topLeft={topLeft} topRight={topRight} />;
  return (
    <div className="relative aspect-video overflow-hidden bg-ink">
      <img
        src={cover.small_url}
        srcSet={`${cover.small_url} 768w, ${cover.url} 1536w`}
        sizes="(max-width: 700px) 100vw, 420px"
        alt=""
        loading="lazy"
        decoding="async"
        className="absolute inset-0 size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
      />
      {(topLeft || topRight) && (
        <div className="absolute top-0 right-0 flex max-w-[75%] flex-wrap items-center justify-end gap-1.5 p-3">
          {topLeft}
          {topRight}
        </div>
      )}
    </div>
  );
};
