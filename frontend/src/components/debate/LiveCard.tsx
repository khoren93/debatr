import type { ReactNode } from 'react';
import { hideStudioMarkers, shortModelName, splitEmotionTag } from '../../lib/format';
import { PlayerFrame, PlayerShell } from './PlayerShell';
import type { SpeakerInfo } from './helpers';
import { ModelLogo } from './SpeakerTile';

interface Props {
  status: 'queued' | 'running';
  topic: string;
  /** "ROUND 1" / "VERDICT" of the turn being written (or the last one). */
  roundLabel: string | null;
  debaters: SpeakerInfo[];
  /** Who is writing right now (null between turns). */
  speaker: SpeakerInfo | null;
  /** Text streamed so far for the current turn. */
  text: string;
  /** Some turns are done already. */
  started: boolean;
  /** Between turns: the studio designs the last turn's scenes or fact-checks them. */
  studio?: 'designing' | 'checking' | null;
  /** Overview of the turns so far, under the frame. */
  overview: ReactNode;
}

const CAPTION_WORDS = 8;

/** Equaliser bars of the speaking chip. */
const Bars = ({ color }: { color: string }) => (
  <span className="flex h-[1.8cqw] items-end gap-[0.25cqw]" aria-hidden="true">
    {[0, 0.2, 0.4, 0.1].map((delay) => (
      <span key={delay} className="h-full w-[0.3cqw] origin-bottom animate-bars" style={{ background: color, animationDelay: `${delay}s` }} />
    ))}
  </span>
);

const DebaterCard = ({ d, speaking }: { d: SpeakerInfo; speaking: boolean }) => (
  <div
    className="grid w-full max-w-[17cqw] justify-items-center gap-[0.5cqw] rounded-[1.8cqw] border bg-surface/72 px-[1.2cqw] py-[1.8cqw] text-center transition-all duration-300"
    style={{ borderColor: speaking ? d.color : 'rgba(255,255,255,0.08)', boxShadow: speaking ? `0 0 0 0.4cqw ${d.color}38, 0 2cqw 5cqw -2cqw ${d.color}` : 'none', opacity: speaking ? 1 : 0.72 }}
  >
    <div className="grid size-[5.6cqw] place-items-center overflow-hidden rounded-[1.6cqw] border" style={{ background: `${d.color}29`, borderColor: speaking ? d.color : 'rgba(255,255,255,0.08)' }}>
      <ModelLogo model={d.model} />
    </div>
    <div className="mt-[0.4cqw] max-w-full truncate font-display text-[1.9cqw] font-bold tracking-[-0.02em]">{d.name}</div>
    <div className="max-w-full truncate font-mono text-[1cqw] text-muted">{shortModelName(d.model)}</div>
    <div className="font-mono text-[0.9cqw] tracking-[0.12em]" style={{ color: speaking ? d.color : '#5C6170' }}>
      {speaking ? 'SPEAKING' : d.tag}
    </div>
  </div>
);

/** Player frame while the debate is being generated: the cast, who is speaking, live captions. */
export const LiveCard = ({ status, topic, roundLabel, debaters, speaker, text, started, studio = null, overview }: Props) => {
  const words = splitEmotionTag(hideStudioMarkers(text)).body.split(/\s+/).filter(Boolean);
  const caption = words.slice(-CAPTION_WORDS);
  const statusLine = studio === 'designing' ? 'Drawing the scenes…' : studio === 'checking' ? 'Fact-checking the figures…' : status === 'queued' ? 'Waiting for a worker…' : speaker ? 'Thinking…' : started ? 'Passing the mic…' : 'Warming up…';
  const twoSided = debaters.length === 2;
  const title = (
    <div className={`grid gap-[1.2cqw] text-center ${twoSided ? '' : 'col-span-full'}`}>
      <div className="font-mono text-[1.2cqw] tracking-[0.3em] text-host">{roundLabel ?? 'UP NEXT'}</div>
      <div className="font-display text-[3.6cqw] font-extrabold leading-[1.08] tracking-[-0.03em] text-balance line-clamp-3">{topic}</div>
    </div>
  );
  return (
    <PlayerShell
      frame={
        <PlayerFrame vertical={false} className="bg-[radial-gradient(60%_50%_at_25%_15%,rgba(255,196,107,0.10),transparent_60%),radial-gradient(50%_60%_at_85%_90%,rgba(255,122,102,0.10),transparent_60%),linear-gradient(180deg,#0E1424,#0A0D18)]">
          <div className="absolute inset-x-[2.4cqw] top-[2.2cqw] flex items-center justify-between gap-[1cqw]">
            <span className="whitespace-nowrap rounded-full border border-white/14 px-[1.2cqw] py-[0.6cqw] font-mono text-[1.05cqw] tracking-[0.1em] text-host">{roundLabel ?? (status === 'queued' ? 'QUEUED' : 'STARTING')}</span>
            {speaker && (
              <span className="inline-flex items-center gap-[1cqw] rounded-full border bg-ink/70 py-[0.6cqw] pr-[1.4cqw] pl-[0.6cqw]" style={{ borderColor: speaker.color, boxShadow: `0 0 3cqw ${speaker.color}38` }}>
                <span className="grid size-[3cqw] place-items-center overflow-hidden rounded-full border bg-ink" style={{ borderColor: speaker.color }}>
                  <ModelLogo model={speaker.model} />
                </span>
                <span className="grid">
                  <span className="text-[1.4cqw] font-bold leading-tight">{speaker.name}</span>
                  <span className="font-mono text-[0.85cqw] text-muted">{shortModelName(speaker.model)}</span>
                </span>
                <Bars color={speaker.color} />
              </span>
            )}
            <span className="flex items-center gap-[0.6cqw] whitespace-nowrap font-mono text-[1.05cqw] tracking-[0.1em] text-text">
              <span className="size-[0.7cqw] rounded-full bg-danger animate-pulse-dot" /> LIVE
            </span>
          </div>

          <div className="absolute inset-x-[3cqw] top-[8cqw] bottom-[10cqw] grid content-center items-center gap-[2cqw]" style={{ gridTemplateColumns: twoSided ? '1fr 1.9fr 1fr' : `repeat(${Math.max(1, debaters.length)}, minmax(0, 1fr))` }}>
            {twoSided ? (
              <>
                <div className="flex justify-center">
                  <DebaterCard d={debaters[0]} speaking={speaker?.id === debaters[0].id} />
                </div>
                {title}
                <div className="flex justify-center">
                  <DebaterCard d={debaters[1]} speaking={speaker?.id === debaters[1].id} />
                </div>
              </>
            ) : (
              <>
                {title}
                {debaters.map((d) => (
                  <div key={d.id} className="flex justify-center">
                    <DebaterCard d={d} speaking={speaker?.id === d.id} />
                  </div>
                ))}
              </>
            )}
          </div>

          <div className="absolute inset-x-[4cqw] bottom-[3cqw] flex justify-center">
            <div className="flex flex-wrap justify-center gap-x-[0.28em] rounded-[1.4cqw] bg-[#08090D]/78 px-[2cqw] py-[0.9cqw] font-display text-[2.4cqw] font-bold leading-[1.25]">
              {caption.length > 0 ? (
                caption.map((w, i) => (
                  <span key={`${words.length}-${i}`} style={{ color: i === caption.length - 1 ? '#D9FF3D' : '#F2F3F7' }}>
                    {w}
                  </span>
                ))
              ) : (
                <span className="text-text-3">{statusLine}</span>
              )}
            </div>
          </div>
        </PlayerFrame>
      }
      controls={overview}
    />
  );
};

export default LiveCard;
