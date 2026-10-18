import { Player, type PlayerRef } from '@remotion/player';
import { Maximize, Minimize, Pause, Play, Sparkles, Volume2, VolumeX } from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode, type RefObject } from 'react';
import type { Timeline } from '../../api/timeline';
import type { DebateMedia } from '../../api/types';
import { FPS, LONG_H, LONG_W, SHORT_H, SHORT_W } from '../../video/constants';
import { DebateLong } from '../../video/DebateLong';
import { DebateShort } from '../../video/DebateShort';
import { msToFrame } from '../../video/utils';
import { Button, Progress } from '../ui';
import { chapterAt, msLabel, videoChapters, type Chapter, type VideoFormat } from './helpers';

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
const Frame = ({ vertical, fullscreen, children, className = '' }: { vertical: boolean; fullscreen?: boolean; children: ReactNode; className?: string }) => (
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

// --- Ready player ----------------------------------------------------------------

interface ControlsProps {
  playerRef: RefObject<PlayerRef | null>;
  chapters: Chapter[];
  totalMs: number;
  initialMs: number;
  fullscreen: boolean;
  canFullscreen: boolean;
  onFullscreen: () => void;
  onActiveSeq?: (seq: number | null) => void;
}

/** Control strip of the ready player: seek bar by turns, play, mute, time, speaker, fullscreen. */
const PlayerControls = ({ playerRef, chapters, totalMs, initialMs, fullscreen, canFullscreen, onFullscreen, onActiveSeq }: ControlsProps) => {
  const [ms, setMs] = useState(initialMs);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const engaged = useRef(false);
  const lastSeq = useRef<number | null>(null);

  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;
    const report = (frameMs: number) => {
      if (!engaged.current) return;
      const seq = chapters[chapterAt(chapters, frameMs)]?.seq ?? null;
      if (seq !== lastSeq.current) {
        lastSeq.current = seq;
        onActiveSeq?.(seq);
      }
    };
    const onFrame = ({ detail }: { detail: { frame: number } }) => {
      const frameMs = (detail.frame / FPS) * 1000;
      setMs(frameMs);
      report(frameMs);
    };
    const onPlay = () => {
      engaged.current = true;
      setPlaying(true);
      report((player.getCurrentFrame() / FPS) * 1000);
    };
    const onPause = () => setPlaying(false);
    const onSeeked = ({ detail }: { detail: { frame: number } }) => {
      engaged.current = true;
      const frameMs = (detail.frame / FPS) * 1000;
      setMs(frameMs);
      report(frameMs);
    };
    const onMute = ({ detail }: { detail: { isMuted: boolean } }) => setMuted(detail.isMuted);
    player.addEventListener('frameupdate', onFrame);
    player.addEventListener('play', onPlay);
    player.addEventListener('pause', onPause);
    player.addEventListener('ended', onPause);
    player.addEventListener('seeked', onSeeked);
    player.addEventListener('mutechange', onMute);
    return () => {
      player.removeEventListener('frameupdate', onFrame);
      player.removeEventListener('play', onPlay);
      player.removeEventListener('pause', onPause);
      player.removeEventListener('ended', onPause);
      player.removeEventListener('seeked', onSeeked);
      player.removeEventListener('mutechange', onMute);
    };
  }, [playerRef, chapters, onActiveSeq]);

  const seekMs = (target: number) => playerRef.current?.seekTo(msToFrame(Math.max(0, Math.min(totalMs - 1, target))));
  const index = chapterAt(chapters, ms);
  const current = chapters[index];
  const segments: BarSegment[] = chapters.map((ch) => ({
    key: ch.seq,
    flex: Math.max(1, ch.endMs - ch.startMs),
    color: ch.color,
    title: `${ch.speaker} · ${ch.label}`,
    time: msLabel(ch.startMs),
    fill: Math.max(0, Math.min(1, (ms - ch.startMs) / Math.max(1, ch.endMs - ch.startMs))),
  }));
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowRight: 5000, ArrowLeft: -5000 }[e.key];
    if (step) seekMs(ms + step);
    else if (e.key === 'Home') seekMs(0);
    else if (e.key === 'End') seekMs(totalMs);
    else return;
    e.preventDefault();
  };
  const iconButton = 'grid place-items-center text-text-3 hover:text-text cursor-pointer';

  return (
    <>
      {current && (
        <SegmentBar
          segments={segments}
          head={{ index, within: segments[index].fill }}
          onSeek={(i, within) => seekMs(chapters[i].startMs + within * (chapters[i].endMs - chapters[i].startMs))}
          onKeyDown={onKeyDown}
          ariaLabel="Seek"
          ariaValue={{ now: Math.round(ms / 1000), max: Math.round(totalMs / 1000), text: `${msLabel(ms)} of ${msLabel(totalMs)}, ${current.speaker} · ${current.label}` }}
        />
      )}
      <div className="flex items-center gap-3">
        <button type="button" onClick={(e) => playerRef.current?.toggle(e)} className="grid size-9 shrink-0 place-items-center rounded-full bg-text text-ink hover:bg-white cursor-pointer" aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? <Pause className="size-4 fill-current" /> : <Play className="ml-0.5 size-4 fill-current" />}
        </button>
        <button type="button" onClick={() => (muted ? playerRef.current?.unmute() : playerRef.current?.mute())} className={iconButton} aria-label={muted ? 'Unmute' : 'Mute'}>
          {muted ? <VolumeX className="size-[18px]" /> : <Volume2 className="size-[18px]" />}
        </button>
        <div className="whitespace-nowrap font-mono text-xs text-text-3">
          {msLabel(ms)} / {msLabel(totalMs)}
        </div>
        <div className="min-w-0 flex-1 truncate text-right text-xs text-muted">{current ? `${current.speaker} · ${current.label}` : ''}</div>
        {canFullscreen && (
          <button type="button" onClick={onFullscreen} className={iconButton} aria-label={fullscreen ? 'Exit full screen' : 'Full screen'}>
            {fullscreen ? <Minimize className="size-[18px]" /> : <Maximize className="size-[18px]" />}
          </button>
        )}
      </div>
    </>
  );
};

/** Big play button over the paused video (clicks go through to the player). */
const PausedOverlay = ({ playerRef }: { playerRef: RefObject<PlayerRef | null> }) => {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;
    const on = () => setPlaying(true);
    const off = () => setPlaying(false);
    player.addEventListener('play', on);
    player.addEventListener('pause', off);
    player.addEventListener('ended', off);
    return () => {
      player.removeEventListener('play', on);
      player.removeEventListener('pause', off);
      player.removeEventListener('ended', off);
    };
  }, [playerRef]);
  if (playing) return null;
  return (
    <div className="pointer-events-none absolute inset-0 grid place-items-center">
      <div className="grid size-[clamp(48px,8cqw,84px)] place-items-center rounded-full bg-accent/92 text-ink shadow-[0_20px_50px_-10px_rgba(217,255,61,0.45)]">
        <Play className="ml-[6%] size-[42%] fill-current" />
      </div>
    </div>
  );
};

interface PlayerProps {
  timeline: Timeline;
  mediaBase: string;
  format: VideoFormat;
  highlightIndex: number;
  /** Turn to start at (a transcript click that needed the long video); playback starts there. */
  startSeq: number | null;
  playerRef: RefObject<PlayerRef | null>;
  onActiveSeq?: (seq: number | null) => void;
}

/** The debate video (Remotion Player) with the studio's own controls. */
export const DebatePlayer = ({ timeline, mediaBase, format, highlightIndex, startSeq, playerRef, onActiveSeq }: PlayerProps) => {
  const shellRef = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const isLong = format === 'long';
  const { chapters, totalMs } = videoChapters(timeline, format, highlightIndex);
  const start = startSeq !== null ? chapters.find((c) => c.seq === startSeq) : undefined;
  const initialFrame = start ? msToFrame(start.startMs) : 15;
  const key = `${format}-${highlightIndex}-${start?.seq ?? ''}`;

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement !== null && document.fullscreenElement === shellRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void shellRef.current?.requestFullscreen().catch(() => undefined);
  };

  const common = { ref: playerRef, fps: FPS, controls: false, clickToPlay: true, acknowledgeRemotionLicense: true, initialFrame, autoPlay: Boolean(start), style: { width: '100%', height: '100%' } } as const;
  return (
    <PlayerShell
      shellRef={shellRef}
      vertical={!isLong}
      fullscreen={fullscreen}
      frame={
        <Frame vertical={!isLong} fullscreen={fullscreen}>
          {isLong ? (
            <Player key={`player-${key}`} {...common} component={DebateLong} inputProps={{ timeline, mediaBase }} durationInFrames={msToFrame(totalMs)} compositionWidth={LONG_W} compositionHeight={LONG_H} />
          ) : (
            <Player key={`player-${key}`} {...common} component={DebateShort} inputProps={{ timeline, mediaBase, highlightIndex }} durationInFrames={msToFrame(totalMs)} compositionWidth={SHORT_W} compositionHeight={SHORT_H} />
          )}
          <PausedOverlay key={`overlay-${key}`} playerRef={playerRef} />
        </Frame>
      }
      controls={<PlayerControls key={key} playerRef={playerRef} chapters={chapters} totalMs={totalMs} initialMs={(initialFrame / FPS) * 1000} fullscreen={fullscreen} canFullscreen={document.fullscreenEnabled} onFullscreen={toggleFullscreen} onActiveSeq={onActiveSeq} />}
    />
  );
};

// --- Placeholders ----------------------------------------------------------------

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
        <Frame vertical={false} className="bg-[radial-gradient(60%_50%_at_25%_15%,rgba(255,196,107,0.08),transparent_60%),linear-gradient(180deg,#0E1424,#0A0D18)]">
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
        </Frame>
      }
      controls={overview}
    />
  );
};

export { Frame as PlayerFrame };
