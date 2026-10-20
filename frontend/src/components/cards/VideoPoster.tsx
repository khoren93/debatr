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

/**
 * The long video's first frame in markup (`video/components/Chrome` IntroCard): the brand, the
 * format chip, the debaters' face-off and the question, sized in `cqw` of the 16:9 box. The
 * landing's hero and the debate page's player before the first play (no Remotion needed).
 */
export const VideoPoster = ({ participants, topic, label, questionBottom = '5cqw' }: VideoPosterProps) => {
  const size = headlineSize(topic, 4);
  return (
    <DebateCover
      layout="poster"
      participants={participants}
      topLeft={
        <span className="flex items-center gap-[1.3cqw]">
          <span className="block size-[max(18px,4.4cqw)] [&>svg]:size-full">
            <LogoMark />
          </span>
          <span className="font-display text-[max(10px,2.2cqw)] font-bold tracking-[-0.025em]">{APP_NAME}</span>
        </span>
      }
      topRight={<span className="flex h-[max(18px,4.4cqw)] items-center rounded-full border-2 border-white/14 bg-ink/70 px-[1.5cqw] font-mono text-[max(8px,1.25cqw)] tracking-[0.1em] text-accent">{label}</span>}
    >
      <div className="absolute inset-x-[7%] text-center font-display font-extrabold leading-[1.06] tracking-[-0.03em] text-balance" style={{ bottom: questionBottom, fontSize: `${size}cqw` }}>
        {topic}
      </div>
    </DebateCover>
  );
};
