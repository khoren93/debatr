import type { PlayerRef } from '@remotion/player';
import { Flame } from 'lucide-react';
import { Suspense, lazy, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { countView, isLandingPage, referrerHost } from '../../api/debates';
import { fetchTimeline, getDebateMedia } from '../../api/media';
import type { Timeline } from '../../api/timeline';
import type { GalleryItem } from '../../api/types';
import { formatSpec } from '../../lib/formats';
import { track } from '../../lib/presence';
import { CardStats, VideoPoster } from '../cards';
import { PlayBadge } from '../debate/PlayerShell';

// Browser-only (Remotion): loaded on intent or on the first click, never for the server's HTML.
const DebatePlayer = lazy(() => import('../debate/DebatePlayer'));

interface Loaded {
  timeline: Timeline;
  base: string;
}

/** The AI cover (the landing's largest paint) or the video's first frame in markup. */
const Poster = ({ debate }: { debate: GalleryItem }) =>
  debate.cover ? (
    <img
      src={debate.cover.url}
      srcSet={`${debate.cover.small_url} 768w, ${debate.cover.url} 1536w`}
      sizes="(max-width: 760px) 100vw, 680px"
      alt=""
      fetchPriority="high"
      decoding="async"
      className="absolute inset-0 size-full object-cover"
    />
  ) : (
    <VideoPoster participants={debate.participants} topic={debate.topic} label={formatSpec(debate.format).label} />
  );

/**
 * The landing's hero: the most popular debate of the gallery, playable in place. Like the embed
 * (pages/Embed.tsx), the server's HTML is the poster with a play button; the Remotion player and
 * the audio's timeline load on intent (hover, focus) or on the first click, which also plays it,
 * and the player's controls float over the video. A view counts on the first play; the caption
 * leads to the debate's page.
 */
export const HeroDebate = ({ debate }: { debate: GalleryItem }) => {
  const navigate = useNavigate();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  // Play was asked for before the player was there (it plays once mounted).
  const [deferred, setDeferred] = useState(false);
  const [played, setPlayed] = useState(false);
  const loading = useRef(false);
  const counted = useRef(false);
  const playerRef = useRef<PlayerRef | null>(null);
  const path = debate.path || `/d/${debate.slug}`;

  /** The player's chunk and the audio's timeline, once. */
  const warm = () => {
    if (loading.current) return;
    loading.current = true;
    void import('../debate/DebatePlayer');
    getDebateMedia(debate.id)
      .then(async (media) => {
        if (media.media_status !== 'ready' || !media.urls) throw new Error('No audio');
        setLoaded({ timeline: await fetchTimeline(media.urls.timeline), base: media.urls.base });
      })
      .catch(() => setFailed(true));
  };

  const requestPlay = () => {
    // The video could not be loaded here: the debate's page has it.
    if (failed) {
      void navigate(path);
      return;
    }
    setDeferred(true);
    warm();
  };

  const onPlayed = () => {
    setPlayed(true);
    setDeferred(false);
    if (counted.current) return;
    counted.current = true;
    const landed = isLandingPage();
    countView(debate.id, { place: 'page', referrer: landed ? referrerHost() : '', internal: !landed, ref: '' });
    track('video_play', { format: 'long', place: 'home' }, debate.id);
  };

  const facade = (
    <>
      <div className="absolute inset-0">
        <Poster debate={debate} />
      </div>
      <button
        type="button"
        onClick={requestPlay}
        aria-label={`Play “${debate.topic}”`}
        aria-busy={deferred}
        className="absolute inset-0 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/70"
      >
        <PlayBadge waiting={deferred} />
      </button>
    </>
  );

  return (
    <div className="relative animate-rise" style={{ animationDuration: '0.7s', animationDelay: '0.1s' }}>
      <div className="@container relative aspect-video overflow-hidden rounded-panel border border-line-2 bg-black shadow-[0_40px_80px_-30px_rgba(0,0,0,0.8)]" onPointerEnter={warm} onFocus={warm}>
        {loaded ? (
          <div className="absolute inset-0">
            <Suspense fallback={facade}>
              <DebatePlayer
                embed
                timeline={loaded.timeline}
                mediaBase={loaded.base}
                format="long"
                highlightIndex={0}
                startSeq={null}
                deferred={deferred}
                poster={played ? null : <Poster debate={debate} />}
                onPlay={onPlayed}
                playerRef={playerRef}
              />
            </Suspense>
          </div>
        ) : (
          facade
        )}
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <Link to={path} className="group flex min-w-0 items-center gap-2.5">
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-hot/40 px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] text-hot">
            <Flame className="size-3" /> MOST POPULAR
          </span>
          <span className="truncate text-sm font-semibold text-text-2 transition-colors group-hover:text-text">{debate.topic}</span>
        </Link>
        <span className="shrink-0 text-xs text-muted">
          <CardStats likes={debate.likes} views={debate.views} durationMs={debate.duration_ms} />
        </span>
      </div>
    </div>
  );
};
