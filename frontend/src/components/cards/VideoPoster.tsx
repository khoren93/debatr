import type { Participant } from '../../api/types';
import { APP_NAME } from '../../lib/brand';
import { LogoMark } from '../ui';
import { headlineSize } from '../../video/constants';
import { DebateCover } from './DebateCover';

interface VideoPosterProps {
  participants: Participant[];
  topic: string;
  /** The format chip: "AI DEBATE", "RAP BATTLE". */
  label: string;
  /** Space under the question (the landing keeps it above a floating card). */
  questionBottom?: string;
}

/** The brand lockup and the format chip of a poster's top corners, sized in `cqw`: `scale` 1 =
 *  the 16:9 episode, larger for the narrower Short. */
const Brand = ({ scale }: { scale: number }) => (
  <span className="flex items-center" style={{ gap: `${1.3 * scale}cqw` }}>
    <span className="block [&>svg]:size-full" style={{ width: `max(18px, ${4.4 * scale}cqw)`, height: `max(18px, ${4.4 * scale}cqw)` }}>
      <LogoMark />
    </span>
    <span className="font-display font-bold tracking-[-0.025em]" style={{ fontSize: `max(10px, ${2.2 * scale}cqw)` }}>
      {APP_NAME}
    </span>
  </span>
);

const Chip = ({ label, scale }: { label: string; scale: number }) => (
  <span className="flex items-center rounded-full border-2 border-white/14 bg-ink/70 font-mono tracking-[0.1em] text-accent" style={{ height: `max(18px, ${4.4 * scale}cqw)`, paddingInline: `${1.5 * scale}cqw`, fontSize: `max(8px, ${1.25 * scale}cqw)` }}>
    {label}
  </span>
);

/**
 * The long video's first frame in markup (`video/components/Chrome` IntroCard): the brand, the
 * format chip, the debaters' face-off and the question, sized in `cqw` of the 16:9 box. The
 * landing's hero and the debate page's player before the first play (no Remotion needed).
 */
export const VideoPoster = ({ participants, topic, label, questionBottom = '5cqw' }: VideoPosterProps) => {
  const size = headlineSize(topic, 4);
  return (
    <DebateCover layout="poster" participants={participants} topLeft={<Brand scale={1} />} topRight={<Chip label={label} scale={1} />}>
      <div className="absolute inset-x-[7%] text-center font-display font-extrabold leading-[1.06] tracking-[-0.03em] text-balance" style={{ bottom: questionBottom, fontSize: `${size}cqw` }}>
        {topic}
      </div>
    </DebateCover>
  );
};

/** The Short's first frame in markup (its hook card, `video/DebateShort`), 9:16: the face-off on
 *  top and the question in the lower half (the Short shows its hook there). The embedded Short's
 *  poster. */
export const ShortPoster = ({ participants, topic, label, questionBottom = '12%' }: VideoPosterProps) => (
  <DebateCover layout="short" participants={participants} topLeft={<Brand scale={1.8} />} topRight={<Chip label={label} scale={1.8} />}>
    <div className="absolute inset-x-[7%] top-1/2 grid place-items-center text-center font-display font-extrabold leading-[1.08] tracking-[-0.03em] text-balance" style={{ bottom: questionBottom, fontSize: `${headlineSize(topic, 7.4)}cqw` }}>
      {topic}
    </div>
  </DebateCover>
);
