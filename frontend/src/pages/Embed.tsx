import type { PlayerRef } from '@remotion/player';
import { ArrowUpRight, FileText } from 'lucide-react';
import { Suspense, lazy, useRef, useState, type ReactNode } from 'react';
import { countView } from '../api/debates';
import { fetchTimeline, getDebateMedia } from '../api/media';
import type { Timeline } from '../api/timeline';
import { ShortPoster, VideoPoster } from '../components/cards';
import { msLabel } from '../components/debate/helpers';
import { PlayBadge, PlayerFrame } from '../components/debate/PlayerShell';
import { LogoMark } from '../components/ui';
import { APP_NAME } from '../lib/brand';
import { episodeMs, watchHref, type EmbedDebate, type EmbedOptions } from '../lib/embed';
import { formatSpec } from '../lib/formats';

// Browser-only (Remotion): loaded on intent or on the first click, never for the server's HTML.
const DebatePlayer = lazy(() => import('../components/debate/DebatePlayer'));

/** The full window of the frame on the other page, the video centred in it. `onIntent`: the
 *  pointer came in or the keyboard got there. */
export const EmbedWindow = ({ children, onIntent }: { children: ReactNode; onIntent?: () => void }) => (
  <main className="fixed inset-0 grid place-items-center overflow-hidden bg-black text-text" onPointerEnter={onIntent} onFocus={onIntent}>
    {children}
  </main>
);

/** "Watch on Debatr": the debate's page in a new tab (`?ref=embed`). */
const WatchLink = ({ path, compact = false }: { path: string; compact?: boolean }) => (
  <a
    href={watchHref(path)}
    target="_blank"
    rel="noopener"
    title={`Watch on ${APP_NAME}`}
    className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-black/55 py-1 pr-2.5 pl-1 text-xs font-semibold text-text backdrop-blur-sm hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-accent"
  >
    <LogoMark size={20} />
    <span className={compact ? 'max-[420px]:sr-only' : ''}>
      Watch on <span className="font-display font-bold">{APP_NAME}</span>
    </span>
    <ArrowUpRight className="size-3.5 text-text-3" />
  </a>
);

/** The question as a link to the debate, over the top of the frame. */
const TopicBar = ({ debate }: { debate: EmbedDebate }) => (
  <div className="pointer-events-none bg-linear-to-b from-black/90 via-black/60 to-transparent px-[max(12px,2.4cqw)] pt-[max(10px,2cqw)] pb-[7cqw]">
    <a href={watchHref(debate.path)} target="_blank" rel="noopener" className="pointer-events-auto flex max-w-[78%] items-center gap-2.5 hover:underline">
      <LogoMark size={28} />
      <span className="line-clamp-2 font-display text-[max(13px,2.3cqw)] font-bold leading-tight tracking-[-0.02em] text-balance">{debate.topic}</span>
    </a>
  </div>
);

const Poster = ({ debate, short }: { debate: EmbedDebate; short: boolean }) => {
  const label = formatSpec(debate.format).label;
  if (short) return <ShortPoster participants={debate.participants} topic={debate.topic} label={label} />;
  if (!debate.cover) return <VideoPoster participants={debate.participants} topic={debate.topic} label={label} questionBottom="9cqw" />;
  return <img src={debate.cover.url} srcSet={`${debate.cover.small_url} 768w, ${debate.cover.url} 1536w`} sizes="100vw" alt="" fetchPriority="high" decoding="async" className="absolute inset-0 size-full object-cover" />;
};

interface FacadeProps {
  debate: EmbedDebate;
  short: boolean;
  onPlay?: () => void;
  waiting?: boolean;
  /** Over the poster instead of the play button (a debate without its video yet). */
  notice?: ReactNode;
}

/** What the server sends: the poster, the topic (an AI cover carries a hook instead), the length,
 *  the play button and the way to the debate's page. Sized in `cqw` of the frame. */
const Facade = ({ debate, short, onPlay, waiting = false, notice }: FacadeProps) => {
  const length = short ? null : episodeMs(debate);
  return (
    <PlayerFrame vertical={short} fullscreen reserve={0}>
      <div className={`absolute inset-0 ${notice ? 'opacity-35' : ''}`}>
        <Poster debate={debate} short={short} />
      </div>
      {notice ?? (
        <button type="button" onClick={onPlay} aria-label="Play the video" aria-busy={waiting} className="absolute inset-0 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/70">
          <PlayBadge waiting={waiting} />
        </button>
      )}
      {/* The AI cover shows a hook, not the question: the question goes on top. */}
      {debate.cover && !short && (
        <div className="absolute inset-x-0 top-0">
          <TopicBar debate={debate} />
        </div>
      )}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 px-[2.2cqw] pb-[2cqw]">
        <span className="font-mono text-[11px] tracking-[0.04em] text-text-2">{length ? <span className="rounded-md bg-black/60 px-1.5 py-0.5">{msLabel(length)}</span> : null}</span>
        <span className="pointer-events-auto">
          <WatchLink path={debate.path} compact />
        </span>
      </div>
    </PlayerFrame>
  );
};

interface Loaded {
  timeline: Timeline;
  base: string;
}

/**
 * The player of another site's iframe (`/embed/{slug}`, routes/embed.tsx). The server's HTML is
 * the facade; the Remotion player and the audio's timeline load on intent (hover, focus) or on
 * the first click, which also plays it. Hovering first mounts the player under the poster, so
 * the click itself starts the sound (Safari needs that). A view counts when the video plays: the
 * frame loads with every visit of the other page.
 */
export default function Embed({ debate, options }: { debate: EmbedDebate; options: EmbedOptions }) {
  const short = options.format === 'short';
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  // Play was asked for before the player was there (it plays once mounted).
  const [deferred, setDeferred] = useState(false);
  const [played, setPlayed] = useState(false);
  const loading = useRef(false);
  const counted = useRef(false);
  const playerRef = useRef<PlayerRef | null>(null);

  if (!debate.playable || failed) {
    return (
      <EmbedWindow>
        <Facade
          debate={debate}
          short={short}
          notice={
            <div className="absolute inset-0 grid place-items-center p-6 text-center">
              <div className="grid justify-items-center gap-3">
                <span className="grid size-11 place-items-center rounded-2xl bg-surface-2 text-muted">
                  <FileText className="size-5" />
                </span>
                <div className="font-display text-[max(16px,2.4cqw)] font-bold tracking-tight">{failed ? 'The video could not be loaded' : 'The video is not ready yet'}</div>
                <a href={watchHref(debate.path)} target="_blank" rel="noopener" className="inline-flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-bold text-ink hover:bg-accent-hover">
                  Read it on {APP_NAME} <ArrowUpRight className="size-4" />
                </a>
              </div>
            </div>
          }
        />
      </EmbedWindow>
    );
  }

  /** The player's chunk and the audio's timeline, once. */
  const warm = () => {
    if (loading.current) return;
    loading.current = true;
    void import('../components/debate/DebatePlayer');
    getDebateMedia(debate.id)
      .then(async (media) => {
        if (media.media_status !== 'ready' || !media.urls) throw new Error('No audio');
        setLoaded({ timeline: await fetchTimeline(media.urls.timeline), base: media.urls.base });
      })
      .catch(() => setFailed(true));
  };

  const requestPlay = () => {
    setDeferred(true);
    warm();
  };

  const onPlayed = () => {
    setPlayed(true);
    setDeferred(false);
    if (!counted.current) {
      counted.current = true;
      countView(debate.id);
    }
  };

  const facade = <Facade debate={debate} short={short} onPlay={requestPlay} waiting={deferred} />;
  // The question over the video once the poster has gone (the markup poster shows it itself).
  const header = played || (debate.cover && !short) ? <TopicBar debate={debate} /> : null;
  return (
    <EmbedWindow onIntent={warm}>
      {loaded ? (
        <Suspense fallback={facade}>
          <DebatePlayer
            embed
            timeline={loaded.timeline}
            mediaBase={loaded.base}
            format={options.format}
            highlightIndex={0}
            startSeq={null}
            startMs={options.start * 1000}
            deferred={deferred}
            poster={played ? null : <Poster debate={debate} short={short} />}
            onPlay={onPlayed}
            playerRef={playerRef}
            extra={
              // The header's logo leads there as well when the strip has no room.
              <span className="max-[340px]:hidden">
                <WatchLink path={debate.path} compact />
              </span>
            }
            header={header}
          />
        </Suspense>
      ) : (
        facade
      )}
    </EmbedWindow>
  );
}
