import { Player, type PlayerRef } from '@remotion/player';
import { Maximize, Minimize, Pause, Play, Volume2, VolumeX } from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react';
import { absoluteMediaBase } from '../../api/media';
import type { Timeline } from '../../api/timeline';
import { FPS, LONG_H, LONG_W, SHORT_H, SHORT_W } from '../../video/constants';
import { DebateLong } from '../../video/DebateLong';
import { DebateShort } from '../../video/DebateShort';
import { msToFrame } from '../../video/timing';
import { chapterAt, msLabel, videoChapters, type Chapter, type VideoFormat } from './helpers';
import { PlayBadge, PlayerFrame, PlayerShell, SegmentBar, type BarSegment } from './PlayerShell';

/** The debate video (Remotion Player) with the studio's own controls. Browser-only: pages load it
 *  with `lazy()` inside `<ClientOnly>` and show `PlayerPending` until it is there. */

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
  return playing ? null : <PlayBadge />;
};

interface PlayerProps {
  timeline: Timeline;
  /** The media folder (relative or absolute). */
  mediaBase: string;
  format: VideoFormat;
  highlightIndex: number;
  /** Turn to start at (a transcript click that needed the long video); playback starts there. */
  startSeq: number | null;
  playerRef: RefObject<PlayerRef | null>;
  onActiveSeq?: (seq: number | null) => void;
}

export const DebatePlayer = ({ timeline, mediaBase, format, highlightIndex, startSeq, playerRef, onActiveSeq }: PlayerProps) => {
  const shellRef = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const isLong = format === 'long';
  const { chapters, totalMs } = videoChapters(timeline, format, highlightIndex);
  const start = startSeq !== null ? chapters.find((c) => c.seq === startSeq) : undefined;
  // Frame 0 is the intro's face-off (or the Short's hook card), fully drawn: it is the poster.
  const initialFrame = start ? msToFrame(start.startMs) : 0;
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

  // Remotion fetches the audio and pictures by full URL.
  const base = absoluteMediaBase(mediaBase);
  const common = { ref: playerRef, fps: FPS, controls: false, clickToPlay: true, acknowledgeRemotionLicense: true, initialFrame, autoPlay: Boolean(start), style: { width: '100%', height: '100%' } } as const;
  return (
    <PlayerShell
      shellRef={shellRef}
      vertical={!isLong}
      fullscreen={fullscreen}
      frame={
        <PlayerFrame vertical={!isLong} fullscreen={fullscreen}>
          {isLong ? (
            <Player key={`player-${key}`} {...common} component={DebateLong} inputProps={{ timeline, mediaBase: base }} durationInFrames={msToFrame(totalMs)} compositionWidth={LONG_W} compositionHeight={LONG_H} />
          ) : (
            <Player key={`player-${key}`} {...common} component={DebateShort} inputProps={{ timeline, mediaBase: base, highlightIndex }} durationInFrames={msToFrame(totalMs)} compositionWidth={SHORT_W} compositionHeight={SHORT_H} />
          )}
          <PausedOverlay key={`overlay-${key}`} playerRef={playerRef} />
        </PlayerFrame>
      }
      controls={<PlayerControls key={key} playerRef={playerRef} chapters={chapters} totalMs={totalMs} initialMs={(initialFrame / FPS) * 1000} fullscreen={fullscreen} canFullscreen={document.fullscreenEnabled} onFullscreen={toggleFullscreen} onActiveSeq={onActiveSeq} />}
    />
  );
};

export default DebatePlayer;
