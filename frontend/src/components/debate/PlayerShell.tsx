import { Play, Sparkles } from 'lucide-react';
import { useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent, type ReactNode, type RefObject } from 'react';
import type { Timeline } from '../../api/timeline';
import type { CoverImage, DebateMedia, Participant } from '../../api/types';
import { VideoPoster } from '../cards';
import { Button, Progress, Spinner } from '../ui';
import { msLabel, videoChapters, type VideoFormat } from './helpers';

/** The player's frame, seek bar, poster and placeholders: plain markup that also renders on the
 *  server. The Remotion player itself (DebatePlayer) is browser-only and loaded lazily. */

const GAP = 3; // px between the segments of the seek bar

// --- Shell -----------------------------------------------------------------------

interface ShellProps {
  frame: ReactNode;
  controls: ReactNode;
  vertical?: boolean;
  fullscreen?: boolean;
  shellRef?: RefObject<HTMLDivElement | null>;
}

/** Player card: the dark frame area on top, the control strip below. */
export const PlayerShell = ({ frame, controls, vertical = false, fullscreen = false, shellRef }: ShellProps) => (
  <div ref={shellRef} className={`overflow-hidden bg-ink-2 ${fullscreen ? 'flex h-full w-full flex-col' : 'rounded-panel border border-white/8'}`}>
    <div className={`flex justify-center bg-[#08090C] ${vertical && !fullscreen ? 'p-5' : ''} ${fullscreen ? 'min-h-0 flex-1 items-center' : ''}`}>{frame}</div>
    <div className="grid grid-cols-1 gap-2.5 border-t border-white/6 px-4 py-3">{controls}</div>
  </div>
);

/** Frame with the video's aspect ratio (a phone-sized column for the Short). */
export const PlayerFrame = ({ vertical, fullscreen, children, className = '' }: { vertical: boolean; fullscreen?: boolean; children?: ReactNode; className?: string }) => (
  <div
    className={`@container relative w-full overflow-hidden ${vertical && !fullscreen ? 'max-w-[340px] rounded-[16px]' : ''} ${className}`}
    style={{
      aspectRatio: vertical ? '9 / 16' : '16 / 9',
      // In fullscreen the frame fits between the screen edges and the control strip.
      ...(fullscreen ? { width: `min(100%, calc((100dvh - 96px) * ${vertical ? 9 / 16 : 16 / 9}))` } : {}),
    }}
  >
    {children}
  </div>
);

/** Big play button in the middle of the frame (over the paused video and the poster); `waiting`:
 *  play was asked for and the player is still loading. */
export const PlayBadge = ({ waiting = false }: { waiting?: boolean }) => (
  <div className="pointer-events-none absolute inset-0 grid place-items-center">
    <div className="grid size-[clamp(40px,9cqw,84px)] place-items-center rounded-full bg-accent/92 text-ink shadow-[0_20px_50px_-10px_rgba(217,255,61,0.45)]">
      {waiting ? <Spinner className="size-[46%]" /> : <Play className="ml-[6%] size-[42%] fill-current" />}
    </div>
  </div>
);

// --- Poster ----------------------------------------------------------------------

interface PosterProps {
  /** The debate's AI cover; null: the video's first frame in markup. */
  cover: CoverImage | null;
  participants: Participant[];
  topic: string;
  /** The format chip of the markup poster ("AI DEBATE"). */
  label: string;
}

/** What the long video shows until its first play: the AI cover where the debate has one, else
 *  the video's first frame in markup. In the server's HTML and the page's largest paint (LCP),
 *  so it loads first; the player's chunk comes later (DebateView). */
export const PlayerPoster = ({ cover, participants, topic, label }: PosterProps) =>
  cover ? (
    <img
      src={cover.url}
      srcSet={`${cover.small_url} 768w, ${cover.url} 1536w`}
      sizes="(max-width: 1240px) 100vw, 1180px"
      alt=""
      fetchPriority="high"
      decoding="async"
      className="absolute inset-0 size-full object-cover"
    />
  ) : (
    <VideoPoster participants={participants} topic={topic} label={label} />
  );

/** The poster over the frame with the play button on it. */
export const PosterFace = ({ poster, onPlay, waiting = false }: { poster: ReactNode; onPlay?: (e: MouseEvent<HTMLButtonElement>) => void; waiting?: boolean }) => (
  <>
    <div className="absolute inset-0">{poster}</div>
    <button type="button" onClick={onPlay} aria-label="Play the video" aria-busy={waiting} className="absolute inset-0 cursor-pointer rounded-none outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/70">
      <PlayBadge waiting={waiting} />
    </button>
  </>
);

// --- Seek bar --------------------------------------------------------------------

export interface BarSegment {
  key: number;
  /** Relative length. */
  flex: number;
  color: string;
  /** Tooltip: "Debater 1 · Opening". */
  title: string;
  time?: string;
  /** Played share of the segment, 0..1. */
  fill: number;
  pulse?: boolean;
}

interface BarProps {
  segments: BarSegment[];
  /** Playhead: index of the segment and the position inside it (0..1); null hides it. */
  head?: { index: number; within: number } | null;
  /** Seek bar: pointer position as (segment index, position inside it). */
  onSeek?: (index: number, within: number) => void;
  /** Overview bar: a click picks the segment. */
  onPick?: (key: number) => void;
  onKeyDown?: (e: KeyboardEvent<HTMLDivElement>) => void;
  ariaLabel?: string;
  ariaValue?: { now: number; max: number; text: string };
}

/** Thin bar of turns coloured per speaker, sized by their length: the player's seek bar and the
 *  overview while a debate is live or not voiced yet. */
export const SegmentBar = ({ segments, head = null, onSeek, onPick, onKeyDown, ariaLabel, ariaValue }: BarProps) => {
  const [hover, setHover] = useState(-1);
  const dragging = useRef(false);
  const total = segments.reduce((sum, s) => sum + s.flex, 0) || 1;
  const gaps = GAP * Math.max(0, segments.length - 1);
  const before = (index: number) => segments.slice(0, index).reduce((sum, s) => sum + s.flex, 0);

  /** Segment under the pointer and the position inside it. */
  const locate = (e: PointerEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const unit = (rect.width - gaps) / total;
    let left = 0;
    for (let i = 0; i < segments.length; i++) {
      const width = segments[i].flex * unit;
      if (x < left + width + GAP / 2 || i === segments.length - 1) return { index: i, within: Math.max(0, Math.min(1, (x - left) / width)) };
      left += width + GAP;
    }
    return { index: 0, within: 0 };
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const at = locate(e);
    if (onSeek) {
      dragging.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
      onSeek(at.index, at.within);
    } else onPick?.(segments[at.index].key);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const at = locate(e);
    setHover(at.index);
    if (dragging.current) onSeek?.(at.index, at.within);
  };
  const endDrag = () => {
    dragging.current = false;
  };

  const hovered = hover >= 0 ? segments[hover] : null;
  const hoverCenter = hovered ? Math.max(10, Math.min(90, ((before(hover) + hovered.flex / 2) / total) * 100)) : 0;
  const headLeft = head ? `calc((100% - ${gaps}px) * ${(before(head.index) + segments[head.index].flex * head.within) / total} + ${head.index * GAP}px)` : '0';

  return (
    <div
      className={`relative flex h-4 touch-none items-center outline-none focus-visible:ring-2 focus-visible:ring-accent/60 rounded ${onSeek || onPick ? 'cursor-pointer' : ''}`}
      style={{ gap: GAP }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onPointerLeave={() => setHover(-1)}
      onKeyDown={onKeyDown}
      {...(ariaValue
        ? { role: 'slider', tabIndex: 0, 'aria-label': ariaLabel, 'aria-valuemin': 0, 'aria-valuemax': ariaValue.max, 'aria-valuenow': ariaValue.now, 'aria-valuetext': ariaValue.text }
        : { role: 'list', 'aria-label': ariaLabel })}
    >
      {segments.map((s, i) => (
        <div
          key={s.key}
          className={`relative min-w-[3px] overflow-hidden rounded-[3px] bg-white/14 transition-[height] duration-150 ${s.pulse ? 'animate-pulse-dot' : ''}`}
          style={{ flex: s.flex, height: hover === i ? 8 : 4 }}
          role={ariaValue ? undefined : 'listitem'}
          aria-label={ariaValue ? undefined : s.title}
        >
          <div className="absolute inset-y-0 left-0" style={{ width: `${s.fill * 100}%`, background: s.color }} />
        </div>
      ))}
      {head && <div className="pointer-events-none absolute top-1/2 -mt-1.5 -ml-1.5 size-3 rounded-full bg-text shadow-[0_0_0_3px_rgba(0,0,0,0.4)]" style={{ left: headLeft }} />}
      {hovered && (
        <div className="pointer-events-none absolute bottom-[22px] z-10 -translate-x-1/2 whitespace-nowrap rounded-lg bg-text px-2.5 py-1.5 text-xs font-semibold text-ink shadow-[0_10px_30px_-10px_rgba(0,0,0,0.6)]" style={{ left: `${hoverCenter}%` }}>
          {hovered.title}
          {hovered.time && <span className="ml-1 font-mono text-[11px] font-normal text-dim">{hovered.time}</span>}
        </div>
      )}
    </div>
  );
};

// --- Placeholders ----------------------------------------------------------------

interface PendingProps {
  /** null until the audio's timeline is loaded: the bar then shows `turns` over `durationMs`. */
  timeline: Timeline | null;
  format: VideoFormat;
  highlightIndex: number;
  turns?: BarSegment[];
  durationMs?: number;
  /** Over the frame until the first play (PlayerPoster); null: an empty frame with the button. */
  poster?: ReactNode;
  /** The poster's button or the strip's: ask for the player (and to play once it is there). */
  onPlay?: () => void;
  /** Play was asked for: the buttons spin until the player is there. */
  waiting?: boolean;
}

/** The ready player's layout without the player: server HTML (the facade: poster + play), the
 *  wait for the media and for the player's chunk, so nothing moves when the video appears. */
export const PlayerPending = ({ timeline, format, highlightIndex, turns = [], durationMs = 0, poster = null, onPlay, waiting = false }: PendingProps) => {
  const vertical = format !== 'long';
  const video = timeline ? videoChapters(timeline, format, highlightIndex) : null;
  const totalMs = video?.totalMs ?? durationMs;
  const segments: BarSegment[] = video
    ? video.chapters.map((ch) => ({ key: ch.seq, flex: Math.max(1, ch.endMs - ch.startMs), color: ch.color, title: `${ch.speaker} · ${ch.label}`, time: msLabel(ch.startMs), fill: 0 }))
    : turns.map((t) => ({ ...t, fill: 0 }));
  return (
    <PlayerShell
      vertical={vertical}
      frame={<PlayerFrame vertical={vertical}>{onPlay ? <PosterFace poster={poster} onPlay={onPlay} waiting={waiting} /> : <PlayBadge />}</PlayerFrame>}
      controls={
        <>
          <SegmentBar segments={segments} ariaLabel="Turns" />
          <div className="flex items-center gap-3">
            {onPlay ? (
              <button type="button" onClick={onPlay} className="grid size-9 shrink-0 place-items-center rounded-full bg-text text-ink hover:bg-white cursor-pointer" aria-label="Play" aria-busy={waiting}>
                {waiting ? <Spinner className="size-4" /> : <Play className="ml-0.5 size-4 fill-current" />}
              </button>
            ) : (
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-text/60 text-ink" aria-hidden="true">
                <Play className="ml-0.5 size-4 fill-current" />
              </span>
            )}
            <div className="whitespace-nowrap font-mono text-xs text-text-3">
              {msLabel(0)} / {msLabel(totalMs)}
            </div>
          </div>
        </>
      }
    />
  );
};

interface PlaceholderProps {
  media: DebateMedia | null;
  isOwner: boolean;
  completed: boolean;
  onGenerate: () => void;
  /** Overview of the turns under the frame. */
  overview: ReactNode;
}

/** Frame while the audio is built, or before there is any. */
export const PlayerPlaceholder = ({ media, isOwner, completed, onGenerate, overview }: PlaceholderProps) => {
  const status = media?.media_status ?? 'none';
  const building = status === 'queued' || status === 'running';
  const p = media?.progress;
  return (
    <PlayerShell
      frame={
        <PlayerFrame vertical={false} className="bg-[radial-gradient(60%_50%_at_25%_15%,rgba(255,196,107,0.08),transparent_60%),linear-gradient(180deg,#0E1424,#0A0D18)]">
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            {building ? (
              <>
                <div className="font-mono text-[11px] tracking-[0.1em] text-host">VOICING THE DEBATE · {status.toUpperCase()}</div>
                <div className="font-display text-[clamp(18px,2.4vw,26px)] font-bold tracking-tight">{p?.message || 'Queued'}</div>
                <Progress value={p && p.total > 0 ? p.current / p.total : 0} gradient height={5} className="max-w-sm" />
                <div className="text-xs text-muted">{p && p.total > 0 ? `${p.current} / ${p.total} turns` : 'The video unlocks as soon as the track is mixed'}</div>
              </>
            ) : (
              <>
                <span className="grid size-12 place-items-center rounded-2xl bg-surface-2 text-muted">
                  <Sparkles className="size-5" />
                </span>
                <div className="font-display text-lg font-bold tracking-tight">No audio yet</div>
                <div className="max-w-sm text-sm text-muted">{p?.error ? `The last build failed: ${p.error}` : completed ? 'Voice the debate to unlock the video and the Short.' : 'Audio is produced once the debate has finished.'}</div>
                {isOwner && completed && <Button onClick={onGenerate}>Generate audio</Button>}
              </>
            )}
          </div>
        </PlayerFrame>
      }
      controls={overview}
    />
  );
};
