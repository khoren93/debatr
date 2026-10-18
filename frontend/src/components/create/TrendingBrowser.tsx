import { ArrowUpRight, Check, Dice5, RefreshCw, Search, X } from 'lucide-react';
import { useState } from 'react';
import type { TrendingSource, TrendingTopic } from '../../api/types';
import { useTrendingTopics } from '../../hooks/useTrendingTopics';
import { formatAge, sourceDomain } from '../../lib/format';

interface TrendingBrowserProps {
  /** The topic whose story the wizard holds (highlighted card). */
  isPicked: (topic: TrendingTopic) => boolean;
  /** Link a topic; `all` = the loaded batch (to recognise briefs copied into the angle). */
  onPick: (topic: TrendingTopic, all: TrendingTopic[]) => void;
  /** A click on the picked card unlinks it. */
  onUnpick: () => void;
  /** "Debate it as your own topic" from a search without results. */
  onUseQuery: (query: string) => void;
}

/** Topic categories of services/trending.TOPIC_CATEGORIES with their chip colours. */
const CATEGORIES: Record<string, { label: string; color: string }> = {
  politics: { label: 'Politics', color: '#FF7A66' },
  world: { label: 'World', color: '#4FD1C5' },
  business: { label: 'Business', color: '#52D889' },
  tech: { label: 'Tech & AI', color: '#6C9CFF' },
  science: { label: 'Science', color: '#9C8CFF' },
  health: { label: 'Health', color: '#FF7A9A' },
  culture: { label: 'Culture', color: '#E8D35A' },
  sports: { label: 'Sports', color: '#FF9F5A' },
  lifestyle: { label: 'Lifestyle', color: '#FFC46B' },
};
const categoryOf = (id: string) => CATEGORIES[id] ?? { label: id.charAt(0).toUpperCase() + id.slice(1), color: '#B4B8C6' };

/** Topics per "Show more" page; the batch comes hottest first and stays in that order. */
const PAGE = 10;
const HOT_BADGES = 5;

/** Outlet favicon on a light tile (Google's favicon service, no referrer). */
export const Favicon = ({ url }: { url: string | undefined }) => {
  const domain = sourceDomain(url);
  return (
    <span className="grid size-4 shrink-0 place-items-center overflow-hidden rounded-[4px] bg-text">
      {domain && <img src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`} alt="" width={16} height={16} loading="lazy" referrerPolicy="no-referrer" className="size-4" />}
    </span>
  );
};

const randomOf = <T,>(list: T[]): T | undefined => list[Math.floor(Math.random() * list.length)];

/** "UPDATED TODAY · 07:00" in the viewer's time zone. */
const updatedLabel = (iso: string) => {
  const at = new Date(iso);
  const time = at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const day = new Date();
  if (at.toDateString() === day.toDateString()) return `Updated today · ${time}`;
  day.setDate(day.getDate() - 1);
  if (at.toDateString() === day.toDateString()) return `Updated yesterday · ${time}`;
  return `Updated ${at.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} · ${time}`;
};

const matches = (topic: TrendingTopic, terms: string[]) => {
  const haystack = `${topic.question} ${topic.brief} ${topic.label} ${categoryOf(topic.category).label} ${topic.sources.map((s) => s.outlet).join(' ')}`.toLowerCase();
  return terms.every((t) => haystack.includes(t));
};

const TopicCard = ({ topic, source, selected, badge, onPick }: { topic: TrendingTopic; source: TrendingSource | undefined; selected: boolean; badge: boolean; onPick: () => void }) => {
  const category = categoryOf(topic.category);
  return (
    <div
      className={`group relative flex flex-col gap-2.5 rounded-[16px] border p-4 transition-[border-color,transform,background-color] duration-200 hover:-translate-y-0.5 ${
        selected ? 'border-accent bg-accent/5' : 'border-white/6 bg-surface hover:border-white/22'
      }`}
    >
      {/* The whole card picks the topic; the "Read" link sits above this button. */}
      <button type="button" onClick={onPick} aria-pressed={selected} aria-label={topic.question} title={selected ? 'Click again to unselect' : undefined} className="absolute inset-0 rounded-[16px] cursor-pointer focus-visible:outline-2 focus-visible:outline-accent" />
      <div className="pointer-events-none flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.08em]" style={{ color: category.color }}>
          <span className="size-1.5 rounded-full" style={{ background: category.color }} />
          {category.label}
        </span>
        <span className="flex items-center gap-2">
          {badge && <span className="font-mono text-[10px] tracking-[0.06em] text-hot">▲ #{topic.rank}</span>}
          <span className={`grid size-[22px] place-items-center rounded-full border text-ink transition-colors ${selected ? 'border-accent bg-accent' : 'border-white/16'}`}>
            {selected && <Check className="size-[13px]" strokeWidth={2.5} />}
          </span>
        </span>
      </div>
      <div className="pointer-events-none font-display text-[17px] font-bold leading-[1.22] tracking-[-0.015em] text-balance">{topic.question}</div>
      <p className="pointer-events-none line-clamp-3 text-[13px] leading-normal text-muted">{topic.brief}</p>
      {source && (
        <div className="pointer-events-none mt-auto flex min-w-0 items-center gap-2 border-t border-white/6 pt-3 text-xs text-text-3">
          <Favicon url={source.url} />
          <span className="truncate font-semibold">{source.outlet}</span>
          {source.published_at && <span className="shrink-0 text-dim">· {formatAge(source.published_at)}</span>}
          {topic.outlets > 1 && (
            <span className="shrink-0 text-dim" title={`${topic.outlets} outlets carry this story`}>
              +{topic.outlets - 1}
            </span>
          )}
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer noopener"
            title={source.title}
            className="pointer-events-auto relative ml-auto inline-flex shrink-0 items-center gap-1 font-semibold text-text-3 hover:text-accent"
          >
            Read
            <ArrowUpRight className="size-[13px]" />
          </a>
        </div>
      )}
    </div>
  );
};

/** Step 1, left column: today's news topics with search, categories and Hot / New order. */
export const TrendingBrowser = ({ isPicked, onPick, onUnpick, onUseQuery }: TrendingBrowserProps) => {
  const { data, error, loading, retry } = useTrendingTopics();
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [limit, setLimit] = useState(PAGE);

  const topics = data?.topics ?? [];
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const found = topics.filter((t) => matches(t, terms));
  const inCategory = found.filter((t) => category === 'all' || t.category === category);
  const list = inCategory;
  const shown = list.slice(0, limit);
  const categories = (data?.categories ?? []).filter((c) => c.count > 0);
  const badges = category === 'all' && terms.length === 0;

  const surprise = () => {
    const pool = (list.length ? list : topics).filter((t) => !isPicked(t));
    const topic = randomOf(pool);
    if (topic) onPick(topic, topics);
  };
  const changeCategory = (id: string) => {
    setCategory(id);
    setLimit(PAGE);
  };

  return (
    <div className="grid min-w-0 content-start gap-4">
      <div className="min-w-0">
        {data?.updated_at && (
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.08em] text-accent">
            <span className="size-1.5 rounded-full bg-accent animate-pulse-dot" aria-hidden="true" />
            {updatedLabel(data.updated_at)}
          </div>
        )}
        <h2 className="mt-2 font-display text-[clamp(22px,2.4vw,28px)] font-bold tracking-[-0.025em]">Trending topics</h2>
        <p className="mt-1 text-[13px] text-muted">Debate-ready questions from today's news — each linked to its source.</p>
      </div>

      <div className="flex gap-2">
        <label className="flex h-11 min-w-0 flex-1 items-center gap-2.5 rounded-field border border-line bg-surface px-3.5 text-muted focus-within:border-accent">
          <Search className="size-4 shrink-0" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setLimit(PAGE);
            }}
            placeholder="Search topics, outlets…"
            aria-label="Search topics"
            className="min-w-0 flex-1 bg-transparent text-sm text-text outline-none"
          />
          {query && (
            <button type="button" onClick={() => setQuery('')} className="grid place-items-center text-muted hover:text-text cursor-pointer" aria-label="Clear search">
              <X className="size-[15px]" />
            </button>
          )}
        </label>
        <button
          type="button"
          onClick={surprise}
          disabled={topics.length === 0}
          title="Surprise me"
          aria-label="Surprise me"
          className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-field border border-line-2 bg-surface px-3 text-[13px] font-semibold transition-colors hover:bg-surface-2 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 sm:px-3.5"
        >
          <Dice5 className="size-[18px]" />
          <span className="hidden sm:inline">Surprise me</span>
        </button>
      </div>

      {categories.length > 1 && (
        <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5 min-[1180px]:flex-wrap" role="tablist" aria-label="Categories">
          {[{ id: 'all', count: found.length }, ...categories.map((c) => ({ id: c.id, count: found.filter((t) => t.category === c.id).length }))].map((c) => {
            const on = category === c.id;
            const style = c.id === 'all' ? { label: 'All', color: '#F2F3F7' } : categoryOf(c.id);
            return (
              <button
                key={c.id}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => changeCategory(c.id)}
                className={`inline-flex shrink-0 items-center gap-[7px] whitespace-nowrap rounded-full border px-3 py-[7px] text-[13px] font-semibold transition-colors cursor-pointer ${
                  on ? 'border-text bg-text text-ink' : 'border-line bg-surface text-text-2 hover:border-line-3'
                }`}
              >
                <span className="size-[7px] rounded-full" style={{ background: style.color }} />
                {style.label}
                <span className="font-mono text-[11px] opacity-60">{c.count}</span>
              </button>
            );
          })}
        </div>
      )}

      {loading && (
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,270px),1fr))]" aria-busy="true">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="h-[196px] animate-pulse rounded-[16px] border border-white/6 bg-surface" />
          ))}
        </div>
      )}
      {error && (
        <div className="rounded-[16px] border border-dashed border-line-2 p-6 text-center text-sm text-text-3">
          Could not load today's topics ({error}).{' '}
          <button type="button" onClick={retry} className="inline-flex items-center gap-1 font-semibold text-accent hover:text-accent-hover cursor-pointer">
            <RefreshCw className="size-3.5" /> Retry
          </button>
        </div>
      )}
      {data && topics.length === 0 && (
        <div className="rounded-[16px] border border-dashed border-line-2 p-7 text-center text-sm text-text-3">No trending topics yet today — write your own topic in the panel.</div>
      )}

      {shown.length > 0 && (
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,270px),1fr))]">
          {shown.map((t) => (
            <TopicCard key={t.id} topic={t} source={t.sources[0]} selected={isPicked(t)} badge={badges && t.rank <= HOT_BADGES} onPick={() => (isPicked(t) ? onUnpick() : onPick(t, topics))} />
          ))}
        </div>
      )}

      {topics.length > 0 && list.length === 0 && (
        <div className="grid justify-items-center gap-2.5 rounded-[16px] border border-dashed border-line-2 p-7 text-center">
          <div className="text-sm text-text-3">{query.trim() ? `No topics match “${query.trim()}”.` : 'No topics in this category today.'}</div>
          {query.trim() && (
            <button type="button" onClick={() => onUseQuery(query.trim())} className="text-[13px] font-semibold text-accent hover:text-accent-hover cursor-pointer">
              Debate it as your own topic →
            </button>
          )}
        </div>
      )}

      {list.length > limit && (
        <button
          type="button"
          onClick={() => setLimit((n) => n + PAGE)}
          className="inline-flex h-[42px] items-center gap-2 justify-self-center rounded-field border border-line-2 bg-surface px-5 text-[13px] font-semibold transition-colors hover:bg-surface-2 cursor-pointer"
        >
          Show more <span className="font-mono text-[11px] text-muted">{list.length - limit} left</span>
        </button>
      )}
    </div>
  );
};
