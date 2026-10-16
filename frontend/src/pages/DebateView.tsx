import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, Download, Eye, Lock, Repeat2, ShieldAlert, Share2, Square, Trash2 } from 'lucide-react';
import { getErrorMessage, getErrorStatus } from '../api/client';
import { deleteDebate, getDebate, stopDebate } from '../api/debates';
import { getPublicDebate } from '../api/gallery';
import { absoluteMediaBase } from '../api/media';
import { ACTIVE_STATUSES, type Audience, type DebateDetail, type Turn } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Page } from '../components/layout/AppShell';
import { Button, ConfirmDialog, EmptyState, ErrorBox, LinkButton, PageLoader, Pill, StagePill, useToast } from '../components/ui';
import { AudienceVote } from '../components/debate/AudienceVote';
import { AudioTab } from '../components/debate/AudioTab';
import { ExportsAside } from '../components/debate/ExportsAside';
import { LikeButton } from '../components/debate/LikeButton';
import { LiveCard } from '../components/debate/LiveCard';
import { PlayerCard } from '../components/debate/PlayerCard';
import { RegenerateAudioDialog } from '../components/debate/RegenerateAudioDialog';
import { SharePanel } from '../components/debate/SharePanel';
import { Transcript, type StreamingTurn } from '../components/debate/Transcript';
import { TurnTimeline } from '../components/debate/TurnTimeline';
import { VerdictTab } from '../components/debate/VerdictTab';
import { debateMarkdown, downloadText, prettyVoice, timelineItems, turnColor } from '../components/debate/helpers';
import { useDebateMedia } from '../hooks/useDebateMedia';
import { useDebateStream } from '../hooks/useDebateStream';
import { formatCount, formatDateShort, formatDuration, formatTokens, roundLabel, stageOf } from '../lib/format';

interface Props {
  id?: string;
  slug?: string;
}

type Tab = 'transcript' | 'verdict' | 'audio';

const insertTurn = (turns: Turn[], turn: Turn) => {
  if (turns.some((t) => t.seq_index === turn.seq_index)) return turns;
  return [...turns, turn].sort((a, b) => a.seq_index - b.seq_index);
};

const isNearBottom = () => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 240;

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
  const [format, setFormat] = useState<'long' | 'short'>('long');
  const [highlightIndex, setHighlightIndex] = useState(0);
  const [shareOpen, setShareOpen] = useState(false);
  const [confirm, setConfirm] = useState<'stop' | 'delete' | null>(null);
  const [busy, setBusy] = useState(false);
  const [regenOpen, setRegenOpen] = useState(false);
  // Blind voting: the judge's ruling stays covered until the viewer votes or peeks.
  const [revealed, setRevealed] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [activeSeq, setActiveSeq] = useState<number | null>(null);
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
      setDebate((d) => (d ? { ...d, turns: insertTurn(d.turns, turn) } : d));
      setStreaming(null);
    },
    onTurnError: (turn) => {
      setDebate((d) => (d ? { ...d, turns: insertTurn(d.turns, turn) } : d));
      setStreaming(null);
    },
    onVerdictReady: (e) => setDebate((d) => (d ? { ...d, verdict: e.verdict } : d)),
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

  const exportMarkdown = () => {
    if (!debate) return;
    downloadText(debateMarkdown(debate.title ?? 'Debate', debate.created_at, debate.status, debate.participants, debate.turns), `debate-${debate.id}.md`);
  };

  const selectSegment = (seq: number) => {
    setActiveSeq(seq);
    const seg = timeline?.segments.find((s) => s.seq_index === seq);
    const audio = audioRef.current;
    if (tab === 'audio' && seg && audio) {
      audio.currentTime = seg.start_ms / 1000;
      void audio.play();
      return;
    }
    if (tab !== 'transcript') setTab('transcript');
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

  const participants = debate.participants;
  const stage = stageOf(debate.status, media?.media_status ?? debate.media_status);
  const completed = debate.status === 'completed' || debate.status === 'stopped';
  const mediaBase = media?.urls ? absoluteMediaBase(media.urls.base) : '';
  const items = timelineItems(debate.turns, participants, timeline);
  const verdictTurn = debate.turns.find((t) => t.turn_type === 'verdict') ?? null;
  const judgeVoice = prettyVoice(timeline?.speakers.find((s) => s.role === 'judge')?.voice_id);
  const durationMs = timeline?.total_ms ?? debate.duration_ms;
  const totals = debate.totals;
  const currentSpeaker = streaming ? { name: streaming.speaker_name, color: turnColor({ ...streaming, speaker_id: undefined }, participants) } : null;
  const backTo = slug || !isOwner ? { to: '/gallery', label: 'Gallery' } : { to: '/library', label: 'Library' };
  const audience = debate.engagement.audience;
  const showVote = debate.is_public && audience.reason !== 'not_public' && audience.reason !== 'not_finished';
  const verdictHidden = showVote && !revealed && audience.my_vote === null && audience.reason !== 'owner';
  const reveal = () => setRevealed(true);
  const tabs: { value: Tab; label: string }[] = [
    { value: 'transcript', label: 'Transcript' },
    { value: 'verdict', label: 'Verdict' },
    { value: 'audio', label: 'Audio' },
  ];

  return (
    <Page>
      <Link to={backTo.to} className="inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-text">
        <ArrowLeft className="size-3.5" /> {backTo.label}
      </Link>

      <div className="mt-3.5 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 flex-[1_1_420px]">
          <h1 className="font-display text-[clamp(24px,3vw,38px)] font-extrabold leading-[1.1] tracking-[-0.03em] text-balance">{debate.settings.topic || debate.title}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 font-mono text-xs text-muted">
            <StagePill stage={stage} />
            <span>{formatDateShort(debate.created_at)}</span>
            {durationMs ? <span>{formatDuration(durationMs)}</span> : null}
            <span>{debate.turns.length} turns</span>
            {totals.tokens_in + totals.tokens_out > 0 && (
              <span>
                {formatTokens(totals.tokens_in)} / {formatTokens(totals.tokens_out)} tokens
              </span>
            )}
            {debate.author_name && !isOwner && <span>by {debate.author_name}</span>}
            {isOwner && debate.moderation?.status === 'flagged' && (
              <button type="button" onClick={() => setShareOpen(true)} className="inline-flex items-center gap-1 text-host hover:underline cursor-pointer">
                <ShieldAlert className="size-3" /> in review
              </button>
            )}
            {debate.is_public && (
              <span className="inline-flex items-center gap-1">
                <Eye className="size-3" /> {formatCount(debate.views)} views
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {debate.is_public && <LikeButton debate={debate} onChange={updateLikes} />}
          {isOwner && isActive && (
            <Button variant="danger" size="sm" onClick={() => setConfirm('stop')} icon={<Square className="size-3 fill-current" />}>
              Stop
            </Button>
          )}
          {isOwner && completed && (
            <Button variant="secondary" size="sm" onClick={() => setShareOpen((v) => !v)} icon={<Share2 className="size-3.5" />}>
              Share
            </Button>
          )}
          {completed && (isOwner || debate.is_public) && (
            <LinkButton to={`/create?remix=${debate.id}`} variant="secondary" size="sm" icon={<Repeat2 className="size-3.5" />}>
              Remix
            </LinkButton>
          )}
          <Button variant="secondary" size="sm" onClick={exportMarkdown} disabled={debate.turns.length === 0} icon={<Download className="size-3.5" />}>
            Export MD
          </Button>
          {isOwner && (
            <Button variant="danger" size="sm" onClick={() => setConfirm('delete')} icon={<Trash2 className="size-3.5" />}>
              Delete
            </Button>
          )}
        </div>
      </div>

      {isOwner && shareOpen && <SharePanel debate={debate} onChange={(patch) => setDebate((d) => (d ? { ...d, ...patch } : d))} />}

      {debate.status === 'error' && (
        <ErrorBox className="mt-4">
          <b>The debate stopped with an error.</b> {debate.error_message}
        </ErrorBox>
      )}
      {debate.status === 'stopped' && (
        <div className="mt-4 flex items-center gap-2 text-sm text-muted">
          <Pill color="#8B90A0">Stopped</Pill> The debate was stopped before the verdict.
        </div>
      )}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0">
          {isActive ? (
            <LiveCard status={debate.status === 'queued' ? 'queued' : 'running'} roundLabel={streaming?.round_id ? `LIVE · ${roundLabel(streaming.round_id).toUpperCase()}` : null} speakerName={currentSpeaker?.name ?? null} speakerColor={currentSpeaker?.color ?? '#D9FF3D'} canStop={isOwner} stopping={busy && confirm === 'stop'} onStop={() => setConfirm('stop')} />
          ) : (
            <PlayerCard media={media} timeline={timeline} mediaBase={mediaBase} format={format} onFormat={setFormat} highlightIndex={highlightIndex} isOwner={isOwner} completed={completed} onGenerate={() => setRegenOpen(true)} />
          )}

          <TurnTimeline items={items} activeKey={activeSeq} onSelect={selectSegment} className="mt-3.5" />

          {showVote && <AudienceVote debate={debate} revealed={!verdictHidden} onReveal={reveal} onChange={updateAudience} className="mt-5" />}

          <div className="mt-7 flex gap-[18px] border-b border-line" role="tablist">
            {tabs.map((t) => (
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

          {tab === 'transcript' && <Transcript turns={debate.turns} streaming={streaming} participants={participants} timeline={timeline} markdown={debate.settings.output_style === 'markdown'} isActive={isActive} activeSeq={activeSeq} hideVerdict={verdictHidden} onRevealVerdict={reveal} />}
          {tab === 'verdict' && <VerdictTab verdict={debate.verdict} verdictTurn={verdictTurn} participants={participants} judgeVoice={judgeVoice} isActive={isActive} markdown={debate.settings.output_style === 'markdown'} hidden={verdictHidden} onReveal={reveal} />}
          {tab === 'audio' && <AudioTab media={media} timeline={timeline} isOwner={isOwner} completed={completed} onGenerate={() => setRegenOpen(true)} audioRef={audioRef} />}
          <div ref={bottomRef} />
        </div>

        <ExportsAside debate={debate} media={media} timeline={timeline} mediaBase={mediaBase} highlightIndex={highlightIndex} onHighlightChange={setHighlightIndex} onGenerate={() => setRegenOpen(true)} />
      </div>

      {isOwner && <RegenerateAudioDialog open={regenOpen} onClose={() => setRegenOpen(false)} debate={debate} media={media} onQueued={refreshMedia} />}
      <ConfirmDialog open={confirm === 'stop'} title="Stop this debate?" body="The current turn is cut short and no verdict is given. Credits are charged for what has been generated." confirmLabel="Stop debate" danger busy={busy} onConfirm={stop} onClose={() => setConfirm(null)} />
      <ConfirmDialog open={confirm === 'delete'} title="Delete this debate?" body="The transcript, the verdict and all generated audio are removed permanently." confirmLabel="Delete" danger busy={busy} onConfirm={remove} onClose={() => setConfirm(null)} />
    </Page>
  );
};

export default DebateView;
