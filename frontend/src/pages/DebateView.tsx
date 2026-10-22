import type { PlayerRef } from '@remotion/player';
import { Fragment, Suspense, lazy, startTransition, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { ArrowLeft, MicVocal, Repeat2, RotateCcw, ShieldAlert } from 'lucide-react';
import { getErrorMessage } from '../api/client';
import { countView, deleteDebate, getDebate, isLandingPage, referrerHost, resumeDebate, stopDebate } from '../api/debates';
import { getPublicDebate } from '../api/gallery';
import { debateFilesBase } from '../api/media';
import { ACTIVE_STATUSES, type Audience, type DebateDetail, type Turn } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { Button, ClientOnly, ConfirmDialog, EmptyState, ErrorBox, LinkButton, OfficialMark, Pill, RelativeDate, useToast } from '../components/ui';
import { CardStats } from '../components/cards';
import { AudienceVote } from '../components/debate/AudienceVote';
import { DebateActions } from '../components/debate/DebateActions';
import { DetailsTab } from '../components/debate/DetailsTab';
import { PlayerFrame, PlayerPending, PlayerPlaceholder, PlayerPoster, PlayerShell, SegmentBar, type BarSegment } from '../components/debate/PlayerShell';
import { SpeakerTile } from '../components/debate/SpeakerTile';
import { Transcript, type StreamingTurn } from '../components/debate/Transcript';
import { VersionsStrip } from '../components/debate/VersionsStrip';
import { isJudgeTurn, pinRoutedModel, resumePoint, speakerLineup, speakerOfTurn, speakerTitle, turnColor, turnTypeLabel, videoChapters, type SpeakerInfo, type VideoFormat } from '../components/debate/helpers';
import { useDebateMedia } from '../hooks/useDebateMedia';
import { useDebateStream } from '../hooks/useDebateStream';
import { checkElevenLabsKey } from '../hooks/useElevenLabsKeyStatus';
import { getLocalKey } from '../lib/localKeys';
import { STAGE_COLORS, STAGE_LABELS, roundLabel, shortModelName, stageOf } from '../lib/format';
import { formatSpec } from '../lib/formats';
import { frameToMs, msToFrame } from '../video/timing';
import { track } from '../lib/presence';

// Browser-only (Remotion, the MP4 renderer): loaded after hydration (see ClientOnly; the player:
// the facade below).
const DebatePlayer = lazy(() => import('../components/debate/DebatePlayer'));
const ExportRail = lazy(() => import('../components/debate/ExportRail'));
// Not in the server's HTML of a public page (a folded tab, the owner's dialog, a live run): loaded
// when shown, so the page's first JavaScript stays small.
const VerdictTab = lazy(() => import('../components/debate/VerdictTab'));
const RegenerateAudioDialog = lazy(() => import('../components/debate/RegenerateAudioDialog'));
const LiveCard = lazy(() => import('../components/debate/LiveCard'));

/** Save-Data or a 2G connection: the player's chunk waits for the viewer's intent. */
const saveData = () => {
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection;
  return Boolean(connection?.saveData) || /2g/.test(connection?.effectiveType ?? '');
};

interface Props {
  /** The debate as the route loaded it (server or client loader). */
  initial: DebateDetail;
  /** Whom the server personalised `initial` for (user id, null = anonymous); undefined = the
   *  browser loaded it, so it is the current viewer's. */
  viewer?: string | null;
  id?: string;
  slug?: string;
}

type Tab = 'transcript' | 'verdict' | 'details';

const TABS: { value: Tab; label: string }[] = [
  { value: 'transcript', label: 'Transcript' },
  { value: 'verdict', label: 'Verdict' },
  { value: 'details', label: 'Details' },
];

const insertTurn = (turns: Turn[], turn: Turn) => {
  if (turns.some((t) => t.seq_index === turn.seq_index)) return turns;
  return [...turns, turn].sort((a, b) => a.seq_index - b.seq_index);
};

/** How often the page asks for an AI cover being drawn (it takes about a minute). */
const COVER_POLL_MS = 4000;

const isNearBottom = () => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 240;

const wordCount = (text: string) => text.split(/\s+/).filter(Boolean).length;

/** "Debater 1 PRO vs Debater 2 CON" chips under the title. */
const DebaterChips = ({ debaters }: { debaters: SpeakerInfo[] }) => (
  <div className="flex flex-wrap items-center gap-2">
    {debaters.map((d, i) => (
      <Fragment key={d.id}>
        {i > 0 && <span className="font-mono text-[11px] text-dim">vs</span>}
        <span title={shortModelName(d.model)} className="inline-flex max-w-full items-center gap-2 rounded-full border border-white/8 bg-surface py-1 pr-3 pl-1 text-[13px] font-semibold">
          <SpeakerTile model={d.model} color={d.color} size={24} borderAlpha="80" background="#0A0B0F" />
          <span className="truncate">{d.name}</span>
          <span className="font-mono text-[10px] tracking-[0.06em]" style={{ color: d.color }}>
            {d.tag}
          </span>
        </span>
      </Fragment>
    ))}
  </div>
);

/** Debate page for owners (`/debate/:id`) and public viewers (`/d/:slug`). The route loads the
 *  debate (and shows not found / private); live turns, likes and votes update it here. */
const DebateView = ({ initial, viewer, id, slug }: Props) => {
  const navigate = useNavigate();
  const toast = useToast();
  const { user, loading: authLoading } = useAuth();

  const [debate, setDebate] = useState<DebateDetail>(initial);
  const viewerId = user?.id ?? null;
  // Whose copy `debate` is (likes, vote, owner buttons): the server's guess may be anonymous for
  // a visit from another site whose session the browser only knows after hydration.
  const [loadedFor, setLoadedFor] = useState<string | null | undefined>(viewer);
  const stale = !authLoading && loadedFor !== undefined && loadedFor !== viewerId;
  const [reloadKey, setReloadKey] = useState(0);
  const [streaming, setStreaming] = useState<StreamingTurn | null>(null);
  const [tab, setTab] = useState<Tab>('transcript');
  const [format, setFormat] = useState<VideoFormat>('long');
  const [highlightIndex, setHighlightIndex] = useState(0);
  // A transcript click on a turn outside the Short switches to the long video and starts there.
  const [startSeq, setStartSeq] = useState<number | null>(null);
  const [activeSeq, setActiveSeq] = useState<number | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  // The export panel (and its chunk) exists from its first open on.
  const [railUsed, setRailUsed] = useState(false);
  const [coverFocus, setCoverFocus] = useState(false);
  const [confirm, setConfirm] = useState<'stop' | 'delete' | null>(null);
  const [resuming, setResuming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [regenOpen, setRegenOpen] = useState(false);
  // Blind voting: the judge's ruling stays covered until the viewer votes or peeks.
  const [revealed, setRevealed] = useState(false);
  // Video plays and quarters already reported from this page (lib/presence.ts).
  const reported = useRef(new Set<string>());
  const note = (key: string, report: () => void) => {
    if (reported.current.has(key)) return;
    reported.current.add(key);
    report();
  };
  // The player's facade: the server's HTML has the poster and the play button; the Remotion chunk
  // comes on intent (hover, focus), in idle time after the page's load, or on the first click.
  const [wantPlayer, setWantPlayer] = useState(false);
  // Play was asked for before the player was there (it plays once mounted, see DebatePlayer).
  const [deferred, setDeferred] = useState(false);
  const [played, setPlayed] = useState(false);
  const playerRef = useRef<PlayerRef | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refetch = () => setReloadKey((k) => k + 1);

  // Loading the debate counted no view: the page counts one, with where the visitor came from.
  const isPublic = debate.is_public;
  useEffect(() => {
    if (!isPublic) return;
    const landed = isLandingPage();
    countView(debate.id, { place: 'page', referrer: landed ? referrerHost() : '', internal: !landed, ref: new URLSearchParams(window.location.search).get('ref') ?? '' });
  }, [isPublic, debate.id]);

  // Reload on demand: live events, resume, a finished audio build.
  useEffect(() => {
    if (reloadKey === 0) return;
    let cancelled = false;
    (slug ? getPublicDebate(slug) : getDebate(id ?? ''))
      .then((d) => {
        if (!cancelled) setDebate(d);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id, slug, reloadKey]);

  // The copy belongs to another viewer (signed in after an anonymous render, or signed out).
  useEffect(() => {
    if (!stale) return;
    let cancelled = false;
    (slug ? getPublicDebate(slug) : getDebate(id ?? ''))
      .then((d) => {
        if (cancelled) return;
        setDebate(d);
        setLoadedFor(viewerId);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id, slug, stale, viewerId]);

  const debateId = debate.id;
  const isActive = ACTIVE_STATUSES.includes(debate.status);
  const isOwner = debate.is_owner;
  const { media, timeline, refresh: refreshMedia } = useDebateMedia(debateId);

  // While the owner's AI cover is drawn (about a minute), poll the debate for it.
  const coverStatus = debate.cover.status;
  const drawingCover = isOwner && (coverStatus === 'queued' || coverStatus === 'running');
  useEffect(() => {
    if (!drawingCover || !debateId) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      getDebate(debateId)
        .then((d) => {
          if (cancelled) return;
          setDebate(d);
          if (d.cover.status === 'ready') toast.success('The AI cover is ready');
          else if (d.cover.status === 'error') toast.error(d.cover.error || 'The cover could not be drawn');
        })
        .catch(() => undefined);
    }, COVER_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [drawingCover, debateId, toast]);

  // When the audio build finishes, reload the debate (outputs, duration, verdict winner).
  const mediaStatus = media?.media_status;
  const lastMediaStatus = useRef(mediaStatus);
  useEffect(() => {
    const previous = lastMediaStatus.current;
    lastMediaStatus.current = mediaStatus;
    if ((previous === 'queued' || previous === 'running') && (mediaStatus === 'ready' || mediaStatus === 'error') && debateId) {
      getDebate(debateId)
        .then((d) => setDebate(d))
        .catch(() => undefined);
      if (mediaStatus === 'ready') toast.success('Audio is ready — the video can be rendered now');
    }
  }, [mediaStatus, debateId, toast]);

  // The facade's background load: once the page has loaded, in idle time (the poster is the page's
  // largest paint and the player's chunk is not needed for it), unless the viewer saves data.
  const hasVideo = !isActive && (media?.media_status ?? debate.media_status) === 'ready';
  useEffect(() => {
    if (!hasVideo || saveData()) return;
    let idle: number | undefined;
    let timer: number | undefined;
    const warm = () => startTransition(() => setWantPlayer(true));
    const schedule = () => {
      if (typeof window.requestIdleCallback === 'function') idle = window.requestIdleCallback(warm, { timeout: 4000 });
      else timer = window.setTimeout(warm, 1500);
    };
    if (document.readyState === 'complete') schedule();
    else window.addEventListener('load', schedule, { once: true });
    return () => {
      window.removeEventListener('load', schedule);
      if (idle !== undefined) window.cancelIdleCallback(idle);
      window.clearTimeout(timer);
    };
  }, [hasVideo]);

  useDebateStream(debateId, isActive, {
    onDebateStarted: () => setDebate((d) => ({ ...d, status: 'running' })),
    onTurnStarted: (e) => setStreaming({ ...e, text: '' }),
    onTurnDelta: (e) =>
      setStreaming((prev) =>
        prev && prev.seq_index === e.seq_index
          ? { ...prev, text: prev.text + e.delta }
          : { seq_index: e.seq_index, speaker_name: e.speaker_name ?? 'Speaker', speaker_role: 'debater', turn_type: 'argument', round_id: '', text: e.delta },
      ),
    onTurnCompleted: (turn) => {
      setDebate((d) => ({ ...d, turns: insertTurn(d.turns, turn), participants: pinRoutedModel(d.participants, turn) }));
      setStreaming(null);
    },
    onTurnError: (turn) => {
      setDebate((d) => ({ ...d, turns: insertTurn(d.turns, turn) }));
      setStreaming(null);
    },
    onVerdictReady: (e) => setDebate((d) => ({ ...d, verdict: e.verdict })),
    onTurnVisuals: (e) => setDebate((d) => ({ ...d, turns: d.turns.map((t) => (t.seq_index === e.seq_index ? { ...t, visuals: e.visuals } : t)) })),
    onDebateCompleted: () => {
      setStreaming(null);
      refetch();
      refreshMedia();
    },
    onDebateError: (e) => {
      setStreaming(null);
      setDebate((d) => ({ ...d, status: 'error', error_message: e.message ?? d.error_message }));
      refetch();
    },
    onDebateStopped: () => {
      setStreaming(null);
      setDebate((d) => ({ ...d, status: 'stopped' }));
      window.setTimeout(refetch, 3000);
    },
    onReconnect: refetch,
  });

  // Auto-scroll while live: always on a new turn, only when near the bottom while streaming.
  const turnCount = debate.turns.length;
  useEffect(() => {
    if (isActive) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turnCount, isActive]);
  const streamingLength = streaming?.text.length ?? 0;
  useEffect(() => {
    if (streamingLength > 0 && isNearBottom()) bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [streamingLength]);

  const stop = async () => {
    setBusy(true);
    try {
      await stopDebate(debateId);
      setConfirm(null);
      toast.info('Stopping after the current turn');
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  /** Browser-only keys go along like on the wizard's start (a rejected ElevenLabs key is not sent). */
  const resume = async () => {
    setResuming(true);
    try {
      const keys: { user_provider_key?: string; user_tts_key?: string } = {};
      const openrouterKey = getLocalKey('openrouter');
      if (openrouterKey) keys.user_provider_key = openrouterKey;
      const ttsKey = debate.media_plan?.provider === 'elevenlabs' ? getLocalKey('elevenlabs') : '';
      if (ttsKey && (await checkElevenLabsKey(ttsKey)).status !== 'invalid') keys.user_tts_key = ttsKey;
      await resumeDebate(debate.id, keys);
      toast.success('Resumed: the failed turn runs again');
      refetch();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setResuming(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await deleteDebate(debateId);
      toast.success('Debate deleted');
      navigate('/library');
    } catch (err) {
      toast.error(getErrorMessage(err));
      setBusy(false);
    }
  };

  const updateAudience = (audience: Audience) => {
    if (audience.my_vote) setRevealed(true);
    setDebate((d) => ({ ...d, engagement: { ...d.engagement, audience } }));
  };

  const updateLikes = (likes: number, liked: boolean) => setDebate((d) => ({ ...d, engagement: { ...d.engagement, likes, liked } }));

  const changeFormat = (f: VideoFormat) => {
    if (f === format) return;
    setFormat(f);
    setStartSeq(null);
    setActiveSeq(null);
    setDeferred(false);
    warmPlayer();
  };

  const changeHighlight = (i: number) => {
    setHighlightIndex(i);
    setActiveSeq(null);
  };

  /** Kept in the background (a transition): the poster stays until the chunk is there. */
  const warmPlayer = () => {
    if (!wantPlayer) startTransition(() => setWantPlayer(true));
  };

  /** A click before the player is there: load it and play once it is. */
  const requestPlay = () => {
    setDeferred(true);
    setWantPlayer(true);
  };

  const onPlayed = () => {
    setPlayed(true);
    setDeferred(false);
    note(`${debate.id}:${format}:play`, () => track('video_play', { format }, debate.id));
  };
  // Quarters watched of each video, once per page (the console's "watched to the end").
  const onProgress = (fraction: number) => {
    for (const pct of [25, 50, 75, 100]) {
      if (fraction * 100 < (pct === 100 ? 98 : pct)) break;
      note(`${debate.id}:${format}:${pct}`, () => track('video_progress', { pct, format }, debate.id));
    }
  };

  /** Transcript click: jump the player to the turn (the long video when the Short lacks it).
   *  Before the player is loaded the turn is remembered and the video starts there. */
  const seekToSeq = (seq: number) => {
    if (!timeline) return;
    const chapter = videoChapters(timeline, format, highlightIndex).chapters.find((c) => c.seq === seq);
    const player = playerRef.current;
    if (chapter && player) {
      player.seekTo(msToFrame(chapter.startMs));
      player.play();
      return;
    }
    if (!player) requestPlay();
    setFormat('long');
    setStartSeq(seq);
  };

  const openRegenerate = () => {
    setRailOpen(false);
    setRegenOpen(true);
  };

  const openCover = () => {
    setCoverFocus(true);
    setRailOpen(true);
    setRailUsed(true);
  };

  /** Hover or focus on the toolbar: fetch the export panel's chunk before the click. */
  const warmRail = () => {
    if (!railUsed) void import('../components/debate/ExportRail');
  };

  /** The embed code may start where the page's player is (the Short: its first highlight only,
   *  the one embeds show). */
  const playerPosition = () => {
    const player = playerRef.current;
    if (!player || (format === 'short' && highlightIndex !== 0)) return null;
    return { format, ms: frameToMs(player.getCurrentFrame()) };
  };

  const scrollToTurn = (seq: number) => {
    setTab('transcript');
    window.setTimeout(() => document.getElementById(`turn-${seq}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
  };

  // --- states ------------------------------------------------------------------

  if (debate.status === 'draft') {
    return (
      <Page>
        <EmptyState title="This debate is a draft" text="Finish the setup in the wizard to run it." action={isOwner ? <LinkButton to={`/create?draft=${debate.id}`}>Open in the wizard</LinkButton> : undefined} />
      </Page>
    );
  }

  const { participants } = debate;
  const lineup = speakerLineup(debate, timeline);
  const debaters = lineup.filter((s) => s.tag !== 'HOST' && s.tag !== 'JUDGE');
  const stage = stageOf(debate.status, media?.media_status ?? debate.media_status);
  const completed = debate.status === 'completed' || debate.status === 'stopped';
  const voicing = media?.media_status === 'queued' || media?.media_status === 'running';
  const mediaBase = media?.urls?.base ?? '';
  const verdictTurn = debate.turns.find(isJudgeTurn) ?? null;
  const lastStatus = debate.turns.at(-1)?.visuals?.status;
  const studio = !streaming && (lastStatus === 'designing' || lastStatus === 'checking') ? lastStatus : null;
  const backTo = slug || !isOwner ? { to: '/gallery', label: 'Gallery' } : { to: '/library', label: 'Library' };
  const audience = debate.engagement.audience;
  const showVote = debate.is_public && audience.reason !== 'not_public' && audience.reason !== 'not_finished';
  const verdictHidden = showVote && !revealed && audience.my_vote === null && audience.reason !== 'owner';
  const reveal = () => {
    setRevealed(true);
    track('verdict_reveal', {}, debate.id);
  };
  const topic = debate.settings.topic || debate.title || 'Debate';
  const playable = !isActive && !!timeline && !!media?.urls;
  const voiced = hasVideo;
  // Known from the debate itself, so the toolbar is complete in the server's HTML (nothing moves).
  const canExport = completed && (voiced || !!timeline || isOwner);
  const markdown = debate.settings.output_style === 'markdown';

  // Turns so far as a bar (live, or before the audio exists).
  const overview: BarSegment[] = debate.turns
    .filter((t) => !t.error)
    .map((t) => ({ key: t.seq_index, flex: Math.max(1, wordCount(t.text) / 20), color: turnColor(t, participants), title: `${speakerTitle(t)} · ${turnTypeLabel(t.turn_type, t.round_id, t.round_label)}`, fill: 1 }));
  const lastTurn = debate.turns.at(-1);
  const liveRound = streaming?.round_id ? { id: streaming.round_id, label: streaming.round_label } : lastTurn ? { id: lastTurn.round_id, label: lastTurn.round_label } : null;
  const liveSpeaker = streaming ? (speakerOfTurn(lineup, { ...streaming, speaker_id: undefined }) ?? null) : null;
  if (streaming) {
    overview.push({ key: streaming.seq_index, flex: Math.max(1, wordCount(streaming.text) / 20), color: liveSpeaker?.color ?? '#D9FF3D', title: `${speakerTitle({ ...streaming, speaker_id: undefined })} · writing`, fill: 1, pulse: true });
  }
  const overviewStrip = (
    <>
      {overview.length > 0 ? <SegmentBar segments={overview} onPick={scrollToTurn} ariaLabel="Turns" /> : <div className="h-4" />}
      <div className="flex flex-col items-start gap-1 text-xs text-muted sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <span className="font-mono">
          {debate.turns.length} {debate.turns.length === 1 ? 'turn' : 'turns'}
          {isActive && streaming ? ` · ${speakerTitle({ ...streaming, speaker_id: undefined })} is speaking` : ''}
        </span>
        <span className="max-w-full truncate sm:text-right">{isActive ? 'Audio and video are produced when the debate ends' : 'Click a turn to read it'}</span>
      </div>
    </>
  );

  // With the video ready its markup poster shows the question and the debaters, so the header
  // keeps only the meta line (the question stays the page's heading for screen readers). An AI
  // cover carries a hook, not the question: the header stays.
  const cover = debate.cover.current;
  const posterHeader = voiced && !cover;
  const backLink = (
    <Link to={backTo.to} className="inline-flex w-max items-center gap-2 text-[13px] font-medium text-muted hover:text-text">
      <ArrowLeft className="size-4" /> {backTo.label}
    </Link>
  );
  const show = formatSpec(debate.settings.format);
  // The long video's poster until its first play (a transcript click starts at a turn instead).
  const posterOn = format === 'long' && !played && startSeq === null;
  const poster = <PlayerPoster cover={cover} participants={participants} topic={topic} label={show.label} />;
  const pending = (
    <PlayerPending timeline={timeline} format={format} highlightIndex={highlightIndex} turns={overview} durationMs={debate.duration_ms ?? 0} poster={posterOn ? poster : null} onPlay={requestPlay} waiting={deferred} />
  );
  const meta = (
    <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-xs text-muted">
      {/* A finished debate needs no status: that is what the gallery shows. */}
      {stage !== 'completed' && (
        <span className="inline-flex items-center gap-1.5 font-mono" style={{ color: STAGE_COLORS[stage] }}>
          <span className={`size-1.5 rounded-full ${stage === 'live' || stage === 'rendering' ? 'animate-pulse-dot' : ''}`} style={{ background: STAGE_COLORS[stage] }} />
          {STAGE_LABELS[stage]}
        </span>
      )}
      {show.id === 'rap_battle' && (
        <span className="inline-flex items-center gap-1 font-mono tracking-[0.04em] text-accent">
          <MicVocal className="size-3" /> {show.label}
        </span>
      )}
      <RelativeDate iso={debate.created_at} />
      {debate.is_public && <CardStats likes={debate.engagement.likes} views={debate.views} />}
      {debate.author_name && !isOwner && (
        <span className="inline-flex items-center gap-1">
          by {debate.author_name}
          {debate.author_official && <OfficialMark className="size-3" />}
        </span>
      )}
      {debate.remix_of && (
        <Link to={debate.remix_of.path || `/d/${debate.remix_of.slug}`} title={debate.remix_of.topic} className="inline-flex min-w-0 max-w-[260px] items-center gap-1 hover:text-text">
          <Repeat2 className="size-3 shrink-0" /> <span className="truncate">remix of {debate.remix_of.topic}</span>
        </Link>
      )}
      {isOwner && debate.moderation?.status === 'flagged' && !debate.is_public && (
        <span className="inline-flex items-center gap-1 text-host">
          <ShieldAlert className="size-3" /> in review
        </span>
      )}
    </div>
  );

  return (
    <Page>
      <article className="mx-auto grid w-full max-w-[1180px] gap-[22px]">
        {posterHeader ? (
          // Phones: the meta line has a row of its own, so the server's UTC date turning into
          // "Today" after hydration cannot pull it up next to the back link (a layout shift).
          <header className="flex min-w-0 flex-col items-start gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-4">
            <h1 className="sr-only">{topic}</h1>
            {backLink}
            {meta}
          </header>
        ) : (
          <>
            {backLink}
            <header className="min-w-0">
              <h1 className="font-display text-[clamp(28px,3.4vw,46px)] font-extrabold leading-[1.02] tracking-[-0.035em] text-balance">{topic}</h1>
              <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2.5">
                {debaters.length > 0 && <DebaterChips debaters={debaters} />}
                {meta}
              </div>
            </header>
          </>
        )}

        {debate.status === 'error' && (
          <ErrorBox className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="min-w-0 flex-1">
              <b>The debate stopped with an error.</b> {debate.error_message}
              {isOwner && <div className="mt-1 text-muted">Resume runs turn {resumePoint(debate.turns) + 1} again with the same models and goes on from there. The turns before it stay.</div>}
            </div>
            {isOwner && (
              <Button size="sm" variant="secondary" icon={<RotateCcw className="size-4" />} loading={resuming} disabled={voicing} onClick={() => void resume()}>
                Resume
              </Button>
            )}
          </ErrorBox>
        )}
        {debate.status === 'stopped' && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Pill color="#8B90A0">Stopped</Pill> The debate was stopped before the verdict.
          </div>
        )}

        <div className="grid min-w-0 gap-3">
          <div className="flex flex-wrap items-center gap-3 sm:justify-end" onPointerEnter={warmRail} onFocus={warmRail}>
            <DebateActions
              debate={debate}
              timeline={timeline}
              isActive={isActive}
              completed={completed}
              voicing={voicing}
              railOpen={railOpen}
              canExport={canExport}
              onToggleRail={() => {
                setCoverFocus(false);
                setRailOpen((v) => !v);
                setRailUsed(true);
              }}
              format={voiced ? format : undefined}
              onFormat={changeFormat}
              onLikes={updateLikes}
              onPatch={(patch) => setDebate((d) => ({ ...d, ...patch }))}
              onGenerate={openRegenerate}
              onCover={openCover}
              playerPosition={playerPosition}
              onStop={() => setConfirm('stop')}
              onDelete={() => setConfirm('delete')}
            />
          </div>

          {isActive ? (
            <Suspense fallback={<PlayerShell frame={<PlayerFrame vertical={false} />} controls={overviewStrip} />}>
              <LiveCard
                status={debate.status === 'queued' ? 'queued' : 'running'}
                topic={topic}
                roundLabel={liveRound ? roundLabel(liveRound.id, liveRound.label).toUpperCase() : null}
                debaters={debaters}
                speaker={liveSpeaker}
                text={streaming?.text ?? ''}
                started={debate.turns.length > 0}
                studio={studio}
                overview={overviewStrip}
              />
            </Suspense>
          ) : voiced ? (
            // The facade: the server's HTML and the wait show the player's layout with the poster;
            // the Remotion player replaces it once wanted and its media is loaded (wantPlayer is
            // false on the server and while hydrating, so no ClientOnly is needed). No Suspense
            // around the server's markup: React streams a large boundary after the shell, which
            // would send the poster twice and swap it by script.
            <div className="min-w-0" onPointerEnter={warmPlayer} onFocus={warmPlayer}>
              {wantPlayer && playable && timeline ? (
                <Suspense fallback={pending}>
                  <DebatePlayer
                    timeline={timeline}
                    mediaBase={mediaBase}
                    format={format}
                    highlightIndex={highlightIndex}
                    startSeq={startSeq}
                    deferred={deferred}
                    poster={posterOn ? poster : null}
                    onPlay={onPlayed}
                    onProgress={onProgress}
                    playerRef={playerRef}
                    onActiveSeq={setActiveSeq}
                  />
                </Suspense>
              ) : (
                pending
              )}
            </div>
          ) : (
            <PlayerPlaceholder media={media} isOwner={isOwner} completed={completed} onGenerate={openRegenerate} overview={overviewStrip} />
          )}
        </div>

        {showVote && <AudienceVote debate={debate} debaters={debaters} revealed={!verdictHidden} onReveal={reveal} onChange={updateAudience} />}

        {debate.motion && <VersionsStrip motion={debate.motion} languageCode={debate.settings.language_code} remixId={debate.id} />}

        <div className="min-w-0">
          <div className="flex gap-[22px] border-b border-white/8" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.value}
                type="button"
                role="tab"
                aria-selected={tab === t.value}
                onClick={() => setTab(t.value)}
                className={`-mb-px border-b-2 px-0.5 py-2.5 text-sm font-semibold transition-colors cursor-pointer ${tab === t.value ? 'border-accent text-text' : 'border-transparent text-muted hover:text-text'}`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === 'transcript' && (
            <Transcript
              turns={debate.turns}
              streaming={streaming}
              participants={participants}
              lineup={lineup}
              timeline={timeline}
              mediaBase={mediaBase || debateFilesBase(debate.id)}
              languageCode={debate.settings.language_code}
              markdown={markdown}
              isActive={isActive}
              activeSeq={playable ? activeSeq : null}
              onSeek={voiced && timeline ? seekToSeq : undefined}
              hideVerdict={verdictHidden}
              onRevealVerdict={reveal}
            />
          )}
          {tab === 'verdict' && (
            <Suspense fallback={<div className="min-h-40" />}>
              <VerdictTab verdict={debate.verdict} verdictTurn={verdictTurn} lineup={lineup} isActive={isActive} markdown={markdown} hidden={verdictHidden} onReveal={reveal} show={show.show} />
            </Suspense>
          )}
          {/* In the page even when folded: the lineup, models and facts for search engines. */}
          <div hidden={tab !== 'details'}>
            <DetailsTab debate={debate} lineup={lineup} timeline={timeline} />
          </div>
          <div ref={bottomRef} />
        </div>
      </article>

      {/* A slide-over from its first open on: nothing of it goes into the server's HTML. */}
      {completed && railUsed && (
        <ClientOnly>
          {() => (
            <ExportRail
              open={railOpen}
              onClose={() => setRailOpen(false)}
              debate={debate}
              lineup={lineup}
              media={media}
              timeline={timeline}
              mediaBase={mediaBase}
              format={format}
              onFormat={changeFormat}
              highlightIndex={highlightIndex}
              onHighlightChange={changeHighlight}
              onGenerate={openRegenerate}
              onCover={(cover) => setDebate((d) => ({ ...d, cover }))}
              focusCover={coverFocus}
            />
          )}
        </ClientOnly>
      )}

      {isOwner && regenOpen && (
        <Suspense>
          <RegenerateAudioDialog open onClose={() => setRegenOpen(false)} debate={debate} media={media} onQueued={refreshMedia} />
        </Suspense>
      )}
      <ConfirmDialog open={confirm === 'stop'} title="Stop this debate?" body="The current turn is cut short and no verdict is given. Credits are charged for what has been generated." confirmLabel="Stop debate" danger busy={busy} onConfirm={stop} onClose={() => setConfirm(null)} />
      <ConfirmDialog open={confirm === 'delete'} title="Delete this debate?" body="The transcript, the verdict and all generated audio are removed permanently." confirmLabel="Delete" danger busy={busy} onConfirm={remove} onClose={() => setConfirm(null)} />
    </Page>
  );
};

export default DebateView;
