import type { PlayerRef } from '@remotion/player';
import { Fragment, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, Lock, ShieldAlert } from 'lucide-react';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { deleteDebate, getDebate, stopDebate } from '../api/debates';
import { getPublicDebate } from '../api/gallery';
import { absoluteMediaBase, debateFilesBase } from '../api/media';
import { ACTIVE_STATUSES, type Audience, type DebateDetail, type Turn } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { ConfirmDialog, EmptyState, ErrorBox, LinkButton, PageLoader, Pill, Segmented, useToast } from '../components/ui';
import { AudienceVote } from '../components/debate/AudienceVote';
import { DebateActions } from '../components/debate/DebateActions';
import { DebatePlayer, PlayerPlaceholder, SegmentBar, type BarSegment } from '../components/debate/DebatePlayer';
import { DetailsTab } from '../components/debate/DetailsTab';
import { ExportRail } from '../components/debate/ExportRail';
import { LiveCard } from '../components/debate/LiveCard';
import { RegenerateAudioDialog } from '../components/debate/RegenerateAudioDialog';
import { SpeakerTile } from '../components/debate/SpeakerTile';
import { Transcript, type StreamingTurn } from '../components/debate/Transcript';
import { VerdictTab } from '../components/debate/VerdictTab';
import { isJudgeTurn, pinRoutedModel, speakerLineup, speakerOfTurn, speakerTitle, turnColor, turnTypeLabel, videoChapters, type SpeakerInfo, type VideoFormat } from '../components/debate/helpers';
import { useDebateMedia } from '../hooks/useDebateMedia';
import { useDebateStream } from '../hooks/useDebateStream';
import { STAGE_COLORS, STAGE_LABELS, formatCount, formatDateShort, formatDuration, roundLabel, shortModelName, stageOf } from '../lib/format';
import { msToFrame } from '../video/utils';

interface Props {
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

/** Debate page for owners (`/debate/:id`) and public viewers (`/d/:slug`). */
const DebateView = ({ id, slug }: Props) => {
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const { user, loading: authLoading } = useAuth();

  const [debate, setDebate] = useState<DebateDetail | null>(null);
  const [loadError, setLoadError] = useState<{ status: number | null; message: string } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [streaming, setStreaming] = useState<StreamingTurn | null>(null);
  const [tab, setTab] = useState<Tab>('transcript');
  const [format, setFormat] = useState<VideoFormat>('long');
  const [highlightIndex, setHighlightIndex] = useState(0);
  // A transcript click on a turn outside the Short switches to the long video and starts there.
  const [startSeq, setStartSeq] = useState<number | null>(null);
  const [activeSeq, setActiveSeq] = useState<number | null>(null);
  const [railOpen, setRailOpen] = useState(false);
  const [confirm, setConfirm] = useState<'stop' | 'delete' | null>(null);
  const [busy, setBusy] = useState(false);
  const [regenOpen, setRegenOpen] = useState(false);
  // Blind voting: the judge's ruling stays covered until the viewer votes or peeks.
  const [revealed, setRevealed] = useState(false);
  const playerRef = useRef<PlayerRef | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refetch = () => setReloadKey((k) => k + 1);

  // Wait for the auth probe so the session cookie is settled before the first request.
  useEffect(() => {
    if (authLoading) return;
    let cancelled = false;
    const request = slug ? getPublicDebate(slug) : getDebate(id ?? '');
    request
      .then((d) => {
        if (cancelled) return;
        setDebate(d);
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError({ status: getErrorStatus(err), message: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [id, slug, reloadKey, authLoading]);

  const debateId = debate?.id;
  const isActive = !!debate && ACTIVE_STATUSES.includes(debate.status);
  const isOwner = !!debate?.is_owner;
  const { media, timeline, refresh: refreshMedia } = useDebateMedia(debateId);

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

  useDebateStream(debateId, isActive, {
    onDebateStarted: () => setDebate((d) => (d ? { ...d, status: 'running' } : d)),
    onTurnStarted: (e) => setStreaming({ ...e, text: '' }),
    onTurnDelta: (e) =>
      setStreaming((prev) =>
        prev && prev.seq_index === e.seq_index
          ? { ...prev, text: prev.text + e.delta }
          : { seq_index: e.seq_index, speaker_name: e.speaker_name ?? 'Speaker', speaker_role: 'debater', turn_type: 'argument', round_id: '', text: e.delta },
      ),
    onTurnCompleted: (turn) => {
      setDebate((d) => (d ? { ...d, turns: insertTurn(d.turns, turn), participants: pinRoutedModel(d.participants, turn) } : d));
      setStreaming(null);
    },
    onTurnError: (turn) => {
      setDebate((d) => (d ? { ...d, turns: insertTurn(d.turns, turn) } : d));
      setStreaming(null);
    },
    onVerdictReady: (e) => setDebate((d) => (d ? { ...d, verdict: e.verdict } : d)),
    onTurnVisuals: (e) => setDebate((d) => (d ? { ...d, turns: d.turns.map((t) => (t.seq_index === e.seq_index ? { ...t, visuals: e.visuals } : t)) } : d)),
    onDebateCompleted: () => {
      setStreaming(null);
      refetch();
      refreshMedia();
    },
    onDebateError: (e) => {
      setStreaming(null);
      setDebate((d) => (d ? { ...d, status: 'error', error_message: e.message ?? d.error_message } : d));
      refetch();
    },
    onDebateStopped: () => {
      setStreaming(null);
      setDebate((d) => (d ? { ...d, status: 'stopped' } : d));
      window.setTimeout(refetch, 3000);
    },
    onReconnect: refetch,
  });

  // Auto-scroll while live: always on a new turn, only when near the bottom while streaming.
  const turnCount = debate?.turns.length ?? 0;
  useEffect(() => {
    if (isActive) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turnCount, isActive]);
  const streamingLength = streaming?.text.length ?? 0;
  useEffect(() => {
    if (streamingLength > 0 && isNearBottom()) bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [streamingLength]);

  const stop = async () => {
    if (!debateId) return;
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

  const remove = async () => {
    if (!debateId) return;
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
    setDebate((d) => (d ? { ...d, engagement: { ...d.engagement, audience } } : d));
  };

  const updateLikes = (likes: number, liked: boolean) => setDebate((d) => (d ? { ...d, engagement: { ...d.engagement, likes, liked } } : d));

  const changeFormat = (f: VideoFormat) => {
    if (f === format) return;
    setFormat(f);
    setStartSeq(null);
    setActiveSeq(null);
  };

  const changeHighlight = (i: number) => {
    setHighlightIndex(i);
    setActiveSeq(null);
  };

  /** Transcript click: jump the player to the turn (the long video when the Short lacks it). */
  const seekToSeq = (seq: number) => {
    if (!timeline) return;
    const chapter = videoChapters(timeline, format, highlightIndex).chapters.find((c) => c.seq === seq);
    const player = playerRef.current;
    if (chapter && player) {
      player.seekTo(msToFrame(chapter.startMs));
      player.play();
      return;
    }
    setFormat('long');
    setStartSeq(seq);
  };

  const openRegenerate = () => {
    setRailOpen(false);
    setRegenOpen(true);
  };

  const scrollToTurn = (seq: number) => {
    setTab('transcript');
    window.setTimeout(() => document.getElementById(`turn-${seq}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50);
  };

  // --- states ------------------------------------------------------------------

  if (loadError && !debate) {
    const next = encodeURIComponent(location.pathname + location.search);
    if (loadError.status === 401) {
      navigate(`/login?next=${next}`, { replace: true });
      return null;
    }
    return (
      <Page>
        {loadError.status === 403 ? (
          <EmptyState icon={<Lock className="size-5" />} title="This debate is private" text={user ? 'Only its owner can open it.' : 'Sign in if it is yours.'} action={!user ? <LinkButton to={`/login?next=${next}`}>Sign in</LinkButton> : <LinkButton to="/library" variant="secondary">Your library</LinkButton>} />
        ) : loadError.status === 404 ? (
          <EmptyState title="Debate not found" text="It may have been deleted or unpublished." action={<LinkButton to={slug ? '/gallery' : '/library'} variant="secondary">Back</LinkButton>} />
        ) : (
          <ErrorBox>
            {loadError.message}{' '}
            <button type="button" onClick={refetch} className="ml-2 font-semibold underline underline-offset-2 cursor-pointer">
              Retry
            </button>
          </ErrorBox>
        )}
      </Page>
    );
  }
  if (!debate) {
    return (
      <Page>
        <PageLoader label="Loading debate…" />
      </Page>
    );
  }
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
  const mediaBase = media?.urls ? absoluteMediaBase(media.urls.base) : '';
  const verdictTurn = debate.turns.find(isJudgeTurn) ?? null;
  const durationMs = timeline?.total_ms ?? debate.duration_ms;
  const lastStatus = debate.turns.at(-1)?.visuals?.status;
  const studio = !streaming && (lastStatus === 'designing' || lastStatus === 'checking') ? lastStatus : null;
  const backTo = slug || !isOwner ? { to: '/gallery', label: 'Gallery' } : { to: '/library', label: 'Library' };
  const audience = debate.engagement.audience;
  const showVote = debate.is_public && audience.reason !== 'not_public' && audience.reason !== 'not_finished';
  const verdictHidden = showVote && !revealed && audience.my_vote === null && audience.reason !== 'owner';
  const reveal = () => setRevealed(true);
  const topic = debate.settings.topic || debate.title || 'Debate';
  const playable = !isActive && !!timeline && !!media?.urls;
  const canExport = completed && (!!timeline || isOwner);
  const markdown = debate.settings.output_style === 'markdown';

  // Turns so far as a bar (live, or before the audio exists).
  const overview: BarSegment[] = debate.turns
    .filter((t) => !t.error)
    .map((t) => ({ key: t.seq_index, flex: Math.max(1, wordCount(t.text) / 20), color: turnColor(t, participants), title: `${speakerTitle(t)} · ${turnTypeLabel(t.turn_type, t.round_id)}`, fill: 1 }));
  const liveRound = streaming?.round_id || debate.turns.at(-1)?.round_id;
  const liveSpeaker = streaming ? (speakerOfTurn(lineup, { ...streaming, speaker_id: undefined }) ?? null) : null;
  if (streaming) {
    overview.push({ key: streaming.seq_index, flex: Math.max(1, wordCount(streaming.text) / 20), color: liveSpeaker?.color ?? '#D9FF3D', title: `${speakerTitle({ ...streaming, speaker_id: undefined })} · writing`, fill: 1, pulse: true });
  }
  const overviewStrip = (
    <>
      {overview.length > 0 ? <SegmentBar segments={overview} onPick={scrollToTurn} ariaLabel="Turns" /> : <div className="h-4" />}
      <div className="flex items-center justify-between gap-3 text-xs text-muted">
        <span className="font-mono">
          {debate.turns.length} {debate.turns.length === 1 ? 'turn' : 'turns'}
          {isActive && streaming ? ` · ${speakerTitle({ ...streaming, speaker_id: undefined })} is speaking` : ''}
        </span>
        <span className="truncate text-right">{isActive ? 'Audio and video are produced when the debate ends' : 'Click a turn to read it'}</span>
      </div>
    </>
  );

  return (
    <Page>
      <div className="mx-auto grid w-full max-w-[1180px] gap-[22px]">
        <Link to={backTo.to} className="inline-flex w-max items-center gap-2 text-[13px] font-medium text-muted hover:text-text">
          <ArrowLeft className="size-4" /> {backTo.label}
        </Link>

        <header className="min-w-0">
          <h1 className="max-w-[20ch] font-display text-[clamp(28px,3.4vw,46px)] font-extrabold leading-[1.02] tracking-[-0.035em] text-balance">{topic}</h1>
          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2.5">
            {debaters.length > 0 && <DebaterChips debaters={debaters} />}
            <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 font-mono text-xs text-muted">
              <span className="inline-flex items-center gap-1.5" style={{ color: STAGE_COLORS[stage] }}>
                <span className={`size-1.5 rounded-full ${stage === 'live' || stage === 'rendering' ? 'animate-pulse-dot' : ''}`} style={{ background: STAGE_COLORS[stage] }} />
                {STAGE_LABELS[stage]}
              </span>
              <span>{formatDateShort(debate.created_at)}</span>
              {durationMs ? <span>{formatDuration(durationMs)}</span> : null}
              <span>
                {debate.turns.length} {debate.turns.length === 1 ? 'turn' : 'turns'}
              </span>
              {debate.is_public && <span>{formatCount(debate.views)} {debate.views === 1 ? "view" : "views"}</span>}
              {debate.author_name && !isOwner && <span>by {debate.author_name}</span>}
              {isOwner && debate.moderation?.status === 'flagged' && !debate.is_public && (
                <span className="inline-flex items-center gap-1 text-host">
                  <ShieldAlert className="size-3" /> in review
                </span>
              )}
            </div>
          </div>
        </header>

        {debate.status === 'error' && (
          <ErrorBox>
            <b>The debate stopped with an error.</b> {debate.error_message}
          </ErrorBox>
        )}
        {debate.status === 'stopped' && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Pill color="#8B90A0">Stopped</Pill> The debate was stopped before the verdict.
          </div>
        )}

        <div className="grid min-w-0 gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {playable ? (
              <Segmented
                className="!border-white/6 !bg-surface"
                options={[
                  { value: 'long' as const, label: 'YouTube 16:9' },
                  { value: 'short' as const, label: 'Short 9:16' },
                ]}
                value={format}
                onChange={changeFormat}
              />
            ) : (
              <span />
            )}
            <DebateActions
              debate={debate}
              timeline={timeline}
              isActive={isActive}
              completed={completed}
              voicing={voicing}
              railOpen={railOpen}
              canExport={canExport}
              onToggleRail={() => setRailOpen((v) => !v)}
              onLikes={updateLikes}
              onPatch={(patch) => setDebate((d) => (d ? { ...d, ...patch } : d))}
              onGenerate={openRegenerate}
              onStop={() => setConfirm('stop')}
              onDelete={() => setConfirm('delete')}
            />
          </div>

          {isActive ? (
            <LiveCard
              status={debate.status === 'queued' ? 'queued' : 'running'}
              topic={topic}
              roundLabel={liveRound ? roundLabel(liveRound).toUpperCase() : null}
              debaters={debaters}
              speaker={liveSpeaker}
              text={streaming?.text ?? ''}
              started={debate.turns.length > 0}
              studio={studio}
              overview={overviewStrip}
            />
          ) : playable && timeline ? (
            <DebatePlayer timeline={timeline} mediaBase={mediaBase} format={format} highlightIndex={highlightIndex} startSeq={startSeq} playerRef={playerRef} onActiveSeq={setActiveSeq} />
          ) : (
            <PlayerPlaceholder media={media} isOwner={isOwner} completed={completed} onGenerate={openRegenerate} overview={overviewStrip} />
          )}
        </div>

        {showVote && <AudienceVote debate={debate} debaters={debaters} revealed={!verdictHidden} onReveal={reveal} onChange={updateAudience} />}

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
              onSeek={playable ? seekToSeq : undefined}
              hideVerdict={verdictHidden}
              onRevealVerdict={reveal}
            />
          )}
          {tab === 'verdict' && <VerdictTab verdict={debate.verdict} verdictTurn={verdictTurn} lineup={lineup} isActive={isActive} markdown={markdown} hidden={verdictHidden} onReveal={reveal} />}
          {tab === 'details' && <DetailsTab debate={debate} lineup={lineup} timeline={timeline} />}
          <div ref={bottomRef} />
        </div>
      </div>

      {completed && (
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
        />
      )}

      {isOwner && <RegenerateAudioDialog open={regenOpen} onClose={() => setRegenOpen(false)} debate={debate} media={media} onQueued={refreshMedia} />}
      <ConfirmDialog open={confirm === 'stop'} title="Stop this debate?" body="The current turn is cut short and no verdict is given. Credits are charged for what has been generated." confirmLabel="Stop debate" danger busy={busy} onConfirm={stop} onClose={() => setConfirm(null)} />
      <ConfirmDialog open={confirm === 'delete'} title="Delete this debate?" body="The transcript, the verdict and all generated audio are removed permanently." confirmLabel="Delete" danger busy={busy} onConfirm={remove} onClose={() => setConfirm(null)} />
    </Page>
  );
};

export default DebateView;
