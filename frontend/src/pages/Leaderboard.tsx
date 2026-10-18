import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Trophy } from 'lucide-react';
import type { LeaderboardEntry } from '../api/types';
import { Page, PageTitle } from '../components/layout/AppShell';
import { Button, EmptyState, ErrorBox, LinkButton, ModelIcon, PageLoader, Segmented, Tag } from '../components/ui';
import { useLeaderboard } from '../hooks/useLeaderboard';
import { formatCount, providerOf } from '../lib/format';

type PriceFilter = 'all' | 'free' | 'paid';

const PRICE_OPTIONS: { value: PriceFilter; label: string }[] = [
  { value: 'all', label: 'All models' },
  { value: 'free', label: 'Free' },
  { value: 'paid', label: 'Paid' },
];

/** Below this many votes a rating is still mostly the prior. */
const PROVISIONAL_VOTES = 5;

const record = (wins: number, contests: number) => (contests > 0 ? `${wins}/${contests}` : '—');
const pct = (share: number | null) => (share === null ? '—' : `${Math.round(share * 100)}%`);

const COLS = 'grid-cols-[28px_minmax(0,1fr)_64px] md:grid-cols-[36px_minmax(0,1fr)_76px_96px_90px_90px_96px_80px]';

/** Fact-check accuracy: verified share of the checked figures that got a clear answer. */
const accuracy = (entry: LeaderboardEntry) => {
  const decided = entry.claims_verified + entry.claims_disputed;
  if (entry.claims_checked === 0) return { label: '—', title: 'No fact-checked figures yet' };
  const share = decided > 0 ? `${Math.round((entry.claims_verified / decided) * 100)}%` : '?';
  return {
    label: `${share} · ${entry.claims_checked}`,
    title: `${entry.claims_verified} verified, ${entry.claims_disputed} disputed, ${entry.claims_checked - decided} unverified of ${entry.claims_checked} fact-checked figures`,
  };
};

/** `rank` is null for models no audience vote has touched yet: they have no place and no rating. */
const Row = ({ entry, rank }: { entry: LeaderboardEntry; rank: number | null }) => {
  const provisional = entry.votes < PROVISIONAL_VOTES;
  const provider = providerOf(entry.model_id);
  return (
    <Link
      to={`/gallery?model=${encodeURIComponent(entry.model_id)}`}
      className={`grid ${COLS} items-center gap-3 border-t border-line px-4 py-3.5 transition-colors hover:bg-surface-2`}
      title={`Public debates with ${entry.name}`}
    >
      <span className={`font-mono text-sm ${rank !== null && rank <= 3 ? 'font-bold text-accent' : 'text-muted'}`}>{rank ?? '—'}</span>
      <span className="flex min-w-0 items-center gap-3">
        <ModelIcon modelId={entry.model_id} size={18} tile />
        <span className="min-w-0">
          <span className="flex items-center gap-2">
            <span className="truncate text-sm font-bold">{entry.name}</span>
            {entry.is_free && <Tag className="shrink-0 !text-ok">FREE</Tag>}
          </span>
          <span className="mt-0.5 block truncate text-[11px] text-muted">
            {provider || entry.model_id}
            <span className="md:hidden">
              {' '}
              · {formatCount(entry.votes)} {entry.votes === 1 ? 'vote' : 'votes'} · {entry.debates} {entry.debates === 1 ? 'debate' : 'debates'}
            </span>
          </span>
        </span>
      </span>
      {entry.rated ? (
        <span className="text-right" title={provisional ? `Provisional: fewer than ${PROVISIONAL_VOTES} audience votes` : undefined}>
          <span className={`font-display text-lg font-bold ${provisional ? 'text-text-3' : ''}`}>{entry.rating}</span>
          {provisional && <span className="block font-mono text-[9px] tracking-[0.08em] text-dim">PROVISIONAL</span>}
        </span>
      ) : (
        <span className="text-right" title="No audience votes in its debates yet">
          <span className="font-display text-lg font-bold text-dim">—</span>
          <span className="block font-mono text-[9px] tracking-[0.08em] text-dim">NO VOTES</span>
        </span>
      )}
      <span className="hidden text-right font-mono text-[13px] md:block">
        {formatCount(entry.votes)} <span className="text-muted">· {pct(entry.vote_share)}</span>
      </span>
      <span className="hidden text-right font-mono text-[13px] md:block">{record(entry.audience_wins, entry.audience_contests)}</span>
      <span className="hidden text-right font-mono text-[13px] md:block">{record(entry.judge_wins, entry.judge_contests)}</span>
      <span className={`hidden text-right font-mono text-[13px] md:block ${entry.claims_disputed > entry.claims_verified ? 'text-con' : ''}`} title={accuracy(entry).title}>
        {accuracy(entry).label}
      </span>
      <span className="hidden text-right font-mono text-[13px] text-accent md:block">{entry.debates} →</span>
    </Link>
  );
};

/** Models ranked by audience votes on public debates. */
const Leaderboard = () => {
  const { data, error, loading, retry } = useLeaderboard();
  const [price, setPrice] = useState<PriceFilter>('all');

  const entries = (data?.entries ?? []).filter((e) => price === 'all' || (price === 'free') === e.is_free);
  // The API lists rated models first; the rest only argued in debates nobody voted on yet.
  const rated = entries.filter((e) => e.rated);
  const unrated = entries.filter((e) => !e.rated);

  const renderBody = () => {
    if (error) {
      return (
        <div className="mt-6 flex flex-col items-start gap-3">
          <ErrorBox className="w-full">Could not load the ranking: {error}</ErrorBox>
          <Button variant="secondary" onClick={retry}>
            Try again
          </Button>
        </div>
      );
    }
    if (loading || !data) return <PageLoader label="Counting the votes…" />;
    if (data.entries.length === 0) {
      return (
        <EmptyState
          className="mt-6"
          icon={<Trophy className="size-5" />}
          title="No public debates yet"
          text="Models show up here once a debate they argued in is published to the gallery."
          action={<LinkButton to="/create">Create a debate</LinkButton>}
        />
      );
    }
    if (entries.length === 0) {
      return <EmptyState className="mt-6" icon={<Trophy className="size-5" />} title={`No ${price} models ranked yet`} text="None of the public debates used one so far." />;
    }
    return (
      <div className="mt-5 overflow-hidden rounded-panel border border-line bg-surface">
        <div className={`grid ${COLS} gap-3 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted`}>
          <span>#</span>
          <span>Model</span>
          <span className="text-right">Rating</span>
          <span className="hidden text-right md:block" title="Audience votes received · share of all votes in its debates">
            Votes
          </span>
          <span className="hidden text-right md:block" title="Debates where the audience picked it, out of debates that got votes">
            Crowd wins
          </span>
          <span className="hidden text-right md:block" title="Debates the AI judge gave it, out of decided debates">
            Judge wins
          </span>
          <span className="hidden text-right md:block" title="Share of its on-screen figures the web fact-check confirmed · figures checked">
            Accuracy
          </span>
          <span className="hidden text-right md:block">Debates</span>
        </div>
        {rated.map((entry, i) => (
          <Row key={entry.model_id} entry={entry} rank={i + 1} />
        ))}
        {rated.length > 0 && unrated.length > 0 && (
          <div className="border-t border-line bg-surface-2/50 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
            Not rated yet · no audience votes in their debates
          </div>
        )}
        {unrated.map((entry) => (
          <Row key={entry.model_id} entry={entry} rank={null} />
        ))}
      </div>
    );
  };

  return (
    <Page>
      <PageTitle kicker="Public" title="Model ranking" right={<Segmented options={PRICE_OPTIONS} value={price} onChange={setPrice} size="sm" />} />
      <p className="mt-3 max-w-[720px] text-sm leading-[1.55] text-muted text-pretty">
        Which model argues best — by audience votes, not the AI judge. Elo-like ratings, 1000 is average.
        {data && (
          <span className="text-text-3">
            {' '}
            {formatCount(data.total_debates)} public debates · {formatCount(data.total_votes)} votes so far.
          </span>
        )}
      </p>
      {data && data.entries.length > 0 && !data.entries.some((e) => e.rated) && (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-panel border border-line bg-surface px-4 py-3.5 text-sm text-text-3">
          <span>No audience votes yet, so no model has a rating. Open a public debate, watch it and pick who argued better — the ranking starts with the first votes.</span>
          <LinkButton to="/gallery" variant="secondary" size="sm">
            Vote in the gallery
          </LinkButton>
        </div>
      )}
      {renderBody()}
    </Page>
  );
};

export default Leaderboard;
