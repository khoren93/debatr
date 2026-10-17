import { useEffect, useState, type ReactNode } from 'react';
import { Heart, Mic, Plus, Search, ShieldAlert } from 'lucide-react';
import { getErrorMessage } from '../api/client';
import { listDebates } from '../api/debates';
import type { DebateSummary, MediaOutput } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Page, PageTitle } from '../components/layout/AppShell';
import { DebateCard, DurationChip, VerdictLine } from '../components/cards';
import { Button, EmptyState, ErrorBox, Input, LinkButton, PageLoader, SectionLabel, Segmented, StagePill, Tag, type SegmentOption } from '../components/ui';
import { formatCount, formatDateShort, formatMoney, stageOfSummary } from '../lib/format';

type Filter = 'all' | 'live' | 'completed' | 'rendering' | 'draft';

const FILTERS: SegmentOption<Filter>[] = [
  { value: 'all', label: 'All' },
  { value: 'live', label: 'Live' },
  { value: 'completed', label: 'Completed' },
  { value: 'rendering', label: 'Rendering' },
  { value: 'draft', label: 'Drafts' },
];

const OUTPUT_ORDER: MediaOutput[] = ['audio', 'video', 'short'];
const OUTPUT_TAGS: Record<MediaOutput, string> = { audio: 'MP3', video: 'MP4', short: 'SHORT' };


/** "51 min" / "1 h 12 min" */
const formatWatchTime = (ms: number) => {
  const totalMinutes = Math.round(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours} h ${minutes} min` : `${totalMinutes} min`;
};

const StatTile = ({ label, value }: { label: ReactNode; value: ReactNode }) => (
  <div className="rounded-[14px] border border-line bg-surface px-[18px] py-4">
    <SectionLabel>{label}</SectionLabel>
    <div className="mt-1.5 font-display text-[26px] font-bold tracking-[-0.02em]">{value}</div>
  </div>
);

const NewDebateButton = () => (
  <LinkButton to="/create" icon={<Plus className="size-4" strokeWidth={2.5} />}>
    New debate
  </LinkButton>
);

const Library = () => {
  const { user } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ attempt: number; rows: DebateSummary[] } | null>(null);
  const [failure, setFailure] = useState<{ attempt: number; message: string } | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    listDebates()
      .then((rows) => {
        if (!cancelled) setResult({ attempt, rows });
      })
      .catch((err: unknown) => {
        if (!cancelled) setFailure({ attempt, message: getErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const debates = result?.attempt === attempt ? result.rows : null;
  const error = failure?.attempt === attempt ? failure.message : null;
  const loading = debates === null && error === null;

  const retry = () => setAttempt((n) => n + 1);

  const renderBody = () => {
    if (loading) return <PageLoader label="Loading your debates…" />;
    if (error !== null || debates === null) {
      return (
        <div className="mt-6 flex flex-col items-start gap-3">
          <ErrorBox className="w-full">Could not load your debates: {error ?? 'unknown error'}</ErrorBox>
          <Button variant="secondary" onClick={retry}>
            Try again
          </Button>
        </div>
      );
    }

    const totalMs = debates.reduce((sum, d) => sum + (d.duration_ms ?? 0), 0);
    const videos = debates.filter((d) => d.outputs.includes('video')).length;
    const needle = query.trim().toLowerCase();
    const visible = debates.filter((d) => {
      if (filter !== 'all' && stageOfSummary(d) !== filter) return false;
      if (!needle) return true;
      return `${d.topic} ${d.title ?? ''}`.toLowerCase().includes(needle);
    });

    return (
      <>
        <div className="mt-[26px] grid grid-cols-[repeat(auto-fit,minmax(min(100%,160px),1fr))] gap-3">
          <StatTile label="Credits" value={user ? formatMoney(user.credits_usd) : '—'} />
          <StatTile label="Debates" value={debates.length} />
          <StatTile label="Videos" value={videos} />
          <StatTile label="Watch time" value={formatWatchTime(totalMs)} />
        </div>

        {debates.length === 0 ? (
          <EmptyState
            className="mt-6"
            icon={<Mic className="size-5" />}
            title="No debates yet"
            text="Pick a question, cast the models and let them argue — your debates and renders will show up here."
            action={<NewDebateButton />}
          />
        ) : (
          <>
            <div className="mt-[26px] flex flex-wrap items-center justify-between gap-3">
              <Segmented options={FILTERS} value={filter} onChange={setFilter} />
              <div className="relative min-w-[180px] max-w-[320px] flex-1">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
                <Input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search topics…" className="pl-10" aria-label="Search topics" />
              </div>
            </div>

            {visible.length === 0 ? (
              <EmptyState className="mt-5" title="Nothing here" text={needle ? `No debates match “${query.trim()}”.` : 'No debates in this state yet.'} />
            ) : (
              <div className="mt-5 grid grid-cols-[repeat(auto-fill,minmax(min(100%,280px),1fr))] gap-4">
                {visible.map((d, i) => {
                  const stage = stageOfSummary(d);
                  const outputs = OUTPUT_ORDER.filter((o) => d.outputs.includes(o));
                  const showVerdict = d.status === 'completed' && d.verdict !== null;
                  return (
                    <DebateCard
                      key={d.id}
                      id={d.id}
                      index={i}
                      to={stage === 'draft' ? `/create?draft=${d.id}` : `/debate/${d.id}`}
                      title={d.topic || d.title || 'Untitled debate'}
                      topLeft={<StagePill stage={stage} />}
                      topRight={<DurationChip ms={d.duration_ms} />}
                      footerLeft={
                        <>
                          <span className="shrink-0">{formatDateShort(d.created_at)}</span>
                          {showVerdict && (
                            <>
                              <span className="text-dim">·</span>
                              <VerdictLine verdict={d.verdict} />
                            </>
                          )}
                        </>
                      }
                      footerRight={
                        outputs.length > 0 || d.is_public || d.moderation_status === 'flagged' ? (
                          <>
                            {d.moderation_status === 'flagged' && !d.is_public && (
                              <span className="mr-1 inline-flex items-center gap-1 text-host" title="Waits for a moderator before it can go public">
                                <ShieldAlert className="size-3" /> review
                              </span>
                            )}
                            {d.is_public && (
                              <span className="mr-1 inline-flex items-center gap-1" title={`${d.likes} likes · ${d.votes} audience votes`}>
                                <Heart className="size-3" /> {formatCount(d.likes)}
                              </span>
                            )}
                            {outputs.map((o) => (
                              <Tag key={o}>{OUTPUT_TAGS[o]}</Tag>
                            ))}
                          </>
                        ) : undefined
                      }
                    />
                  );
                })}
              </div>
            )}
          </>
        )}
      </>
    );
  };

  return (
    <Page>
      <PageTitle kicker="Workspace" title="Your debates" right={<NewDebateButton />} />
      {renderBody()}
    </Page>
  );
};

export default Library;
