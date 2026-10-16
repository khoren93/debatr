import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Trophy } from 'lucide-react';
import type { LeaderboardEntry } from '../api/types';
import { Page, PageTitle } from '../components/layout/AppShell';
import { Button, EmptyState, ErrorBox, LinkButton, PageLoader, Segmented, Tag } from '../components/ui';
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

const COLS = 'grid-cols-[28px_minmax(0,1fr)_64px] md:grid-cols-[36px_minmax(0,1fr)_76px_96px_90px_90px_80px]';

const Row = ({ entry, rank }: { entry: LeaderboardEntry; rank: number }) => {
  const provisional = entry.votes < PROVISIONAL_VOTES;
  const provider = providerOf(entry.model_id);
  return (
    <Link
      to={`/gallery?model=${encodeURIComponent(entry.model_id)}`}
      className={`grid ${COLS} items-center gap-3 border-t border-line px-4 py-3.5 transition-colors hover:bg-surface-2`}
      title={`Public debates with ${entry.name}`}
    >
      <span className={`font-mono text-sm ${rank <= 3 ? 'font-bold text-accent' : 'text-muted'}`}>{rank}</span>
      <span className="min-w-0">
        <span className="flex items-center gap-2">
          <span className="truncate text-sm font-bold">{entry.name}</span>
          {entry.is_free && <Tag className="shrink-0 !text-ok">FREE</Tag>}
        </span>
        <span className="mt-0.5 block truncate text-[11px] text-muted">
          {provider || entry.model_id}
          <span className="md:hidden">
            {' '}
            · {entry.votes} votes · {entry.debates} debates
          </span>
        </span>
      </span>
      <span className="text-right" title={provisional ? `Provisional: fewer than ${PROVISIONAL_VOTES} audience votes` : undefined}>
        <span className={`font-display text-lg font-bold ${provisional ? 'text-text-3' : ''}`}>{entry.rating}</span>
        {provisional && <span className="block font-mono text-[9px] tracking-[0.08em] text-dim">PROVISIONAL</span>}
      </span>
      <span className="hidden text-right font-mono text-[13px] md:block">
        {formatCount(entry.votes)} <span className="text-muted">· {pct(entry.vote_share)}</span>
      </span>
      <span className="hidden text-right font-mono text-[13px] md:block">{record(entry.audience_wins, entry.audience_contests)}</span>
      <span className="hidden text-right font-mono text-[13px] md:block">{record(entry.judge_wins, entry.judge_contests)}</span>
      <span className="hidden text-right font-mono text-[13px] text-accent md:block">{entry.debates} →</span>
    </Link>
  );
};

/** Models ranked by audience votes on public debates. */
const Leaderboard = () => {
  const { data, error, loading, retry } = useLeaderboard();
  const [price, setPrice] = useState<PriceFilter>('all');

  const entries = (data?.entries ?? []).filter((e) => price === 'all' || (price === 'free') === e.is_free);

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
          <span className="hidden text-right md:block">Debates</span>
        </div>
        {entries.map((entry, i) => (
          <Row key={entry.model_id} entry={entry} rank={i + 1} />
        ))}
      </div>
    );
  };

  return (
    <Page>
      <PageTitle kicker="Public" title="Model ranking" right={<Segmented options={PRICE_OPTIONS} value={price} onChange={setPrice} size="sm" />} />
      <p className="mt-3 max-w-[720px] text-sm leading-[1.55] text-muted text-pretty">
        Which model argues best — according to people, not the AI judge. Every audience vote counts as a win of the chosen model over its opponents; ratings are on an Elo-like scale where 1000 is average. Only models with at least one public debate are listed.
        {data && (
          <span className="text-text-3">
            {' '}
            {formatCount(data.total_debates)} public debates · {formatCount(data.total_votes)} votes so far.
          </span>
        )}
      </p>
      {renderBody()}
    </Page>
  );
};

export default Leaderboard;
