import { ArrowRight, ArrowUpRight, Check, Dice5, History, RefreshCw, Search, Sparkles, X } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';
import { getErrorMessage } from '../../api/client';
import { getTopicIdeas } from '../../api/topics';
import type { FormatId, TrendingSource, TrendingTopic } from '../../api/types';
import { useTopicArchive } from '../../hooks/useTopicArchive';
import { useTrendingTopics } from '../../hooks/useTrendingTopics';
import { formatAge, sourceDomain } from '../../lib/format';
import { formatSpec } from '../../lib/formats';
import { Spinner } from '../ui';

interface TrendingBrowserProps {
  /** The wizard's format: its list of news topics and the style of the AI's topics. */
  format: FormatId;
  /** The debate's language, for AI topics on words whose language is unclear. */
  language: string;
  /** The wizard's topic (highlights an AI idea that is in use). */
  topic: string;
  /** The topic whose story the wizard holds (highlighted card). */
  isPicked: (topic: TrendingTopic) => boolean;
  /** Link a topic; `all` = the loaded batch (to recognise briefs copied into the angle). */
  onPick: (topic: TrendingTopic, all: TrendingTopic[]) => void;
  /** A click on the picked card (or AI idea) gives the topic back. */
  onUnpick: () => void;
  /** Make the user's own words (or an AI idea from them) the topic. */
  onUseText: (text: string) => void;
}

/** The AI's topics from the search field's words, for one format. */
interface Ideas {
  format: FormatId;
  text: string;
  status: 'loading' | 'done' | 'error';
  ideas: string[];
  error?: string;
}

/** The AI writes topics from at least this much text (backend TopicIdeasIn). */
const MIN_IDEA_TEXT = 3;
const MAX_QUERY = 300;

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

/** One AI idea: the whole row picks it; a picked one shows a check. */
const IdeaRow = ({ idea, selected, onPick }: { idea: string; selected: boolean; onPick: () => void }) => (
  <button
    type="button"
    onClick={onPick}
    aria-pressed={selected}
    title={selected ? 'Click again to unselect' : 'Use this topic'}
    className={`group flex w-full items-center gap-3 rounded-[12px] border px-3.5 py-3 text-left transition-colors cursor-pointer ${
      selected ? 'border-accent bg-accent/8' : 'border-white/6 bg-ink hover:border-white/22'
    }`}
  >
    <span className="min-w-0 flex-1 font-display text-[15.5px] font-bold leading-[1.25] tracking-[-0.01em] text-balance">{idea}</span>
    <span className={`grid size-[22px] shrink-0 place-items-center rounded-full border text-ink transition-colors ${selected ? 'border-accent bg-accent' : 'border-white/16 group-hover:border-white/30'}`}>
      {selected && <Check className="size-[13px]" strokeWidth={2.5} />}
    </span>
  </button>
);

/** The AI's topics from the user's words: loading rows, the ideas, or why there are none. */
const IdeasPanel = ({
  ideas,
  show,
  topic,
  onUse,
  onUnpick,
  onAgain,
  onClose,
}: {
  ideas: Ideas;
  show: string;
  topic: string;
  onUse: (text: string) => void;
  onUnpick: () => void;
  onAgain: () => void;
  onClose: () => void;
}) => {
  const own = ideas.text.replace(/\??$/, '?');
  return (
    <section className="grid min-w-0 grid-cols-1 gap-2.5 rounded-[16px] border border-accent/30 bg-surface p-3.5" aria-label="AI topics" aria-busy={ideas.status === 'loading'}>
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 shrink-0 text-accent" />
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-text-2">
          {show.charAt(0).toUpperCase() + show.slice(1)} topics from “{ideas.text}”
        </span>
        {ideas.status !== 'loading' && (
          <button type="button" onClick={onAgain} className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-xs font-semibold text-text-3 hover:bg-surface-2 hover:text-text cursor-pointer">
            <RefreshCw className="size-3.5" /> New ideas
          </button>
        )}
        <button type="button" onClick={onClose} aria-label="Close AI topics" className="grid size-6 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-text cursor-pointer">
          <X className="size-3.5" />
        </button>
      </div>
      {ideas.status === 'loading' &&
        Array.from({ length: 3 }, (_, i) => <div key={i} className="h-[50px] animate-pulse rounded-[12px] border border-white/6 bg-ink" />)}
      {ideas.status === 'done' &&
        ideas.ideas.map((idea) => <IdeaRow key={idea} idea={idea} selected={topic.trim() === idea} onPick={() => (topic.trim() === idea ? onUnpick() : onUse(idea))} />)}
      {ideas.status === 'done' && ideas.ideas.length === 0 && <p className="px-1 text-[13px] text-text-3">The AI would not write a topic on this. Try other words.</p>}
      {ideas.status === 'error' && <p className="px-1 text-[13px] text-host">{ideas.error}</p>}
      {ideas.status !== 'loading' && topic.trim() !== own && (
        <button type="button" onClick={() => onUse(own)} className="inline-flex items-center gap-1 justify-self-start px-1 text-[13px] font-semibold text-text-3 hover:text-accent cursor-pointer">
          Use my words as they are <ArrowRight className="size-3.5" />
        </button>
      )}
    </section>
  );
};

/** Step 1, left column: today's news topics for the format, with search, categories and
 * "Surprise me"; a search also finds earlier days' topics (shown below today's), and typing
 * turns the search into the user's own topic, which the AI can sharpen. */
export const TrendingBrowser = ({ format, language, topic, isPicked, onPick, onUnpick, onUseText }: TrendingBrowserProps) => {
  const spec = formatSpec(format);
  const { data, error, loading, retry } = useTrendingTopics(spec.topicList);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [limit, setLimit] = useState(PAGE);
  const [ideas, setIdeas] = useState<Ideas | null>(null);
  const request = useRef(0);

  const archive = useTopicArchive(spec.topicList, query);

  const topics = data?.topics ?? [];
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const searching = terms.length > 0;
  const found = topics.filter((t) => matches(t, terms));
  // Earlier days answer searches only; the last answer is narrowed by the words typed since.
  const earlier = searching ? archive.topics.filter((t) => matches(t, terms) && !topics.some((today) => today.id === t.id)) : [];
  const all = [...found, ...earlier];
  const countIn = (id: string) => all.filter((t) => t.category === id).length;
  const categories = (data?.categories ?? []).filter((c) => countIn(c.id) > 0);
  // Another format's list (or another search) may lack the chosen category: show them all then.
  const activeCategory = categories.some((c) => c.id === category) ? category : 'all';
  const inCategory = (t: TrendingTopic) => activeCategory === 'all' || t.category === activeCategory;
  const list = found.filter(inCategory);
  const earlierList = earlier.filter(inCategory);
  const shown = list.slice(0, limit);
  const shownEarlier = earlierList.slice(0, Math.max(0, limit - list.length));
  const total = list.length + earlierList.length;
  const badges = activeCategory === 'all' && !searching;
  const text = query.trim();
  const canAsk = text.length >= MIN_IDEA_TEXT;
  // Ideas were written for one format; another one asks again.
  const ideasShown = ideas && ideas.format === format ? ideas : null;
  const asking = ideasShown?.status === 'loading';

  /** Ask for topics from the field's words (or, for "New ideas", the words they came from). */
  const askAI = (source = text) => {
    if (source.length < MIN_IDEA_TEXT || asking) return;
    const id = ++request.current;
    setIdeas({ format, text: source, status: 'loading', ideas: [] });
    getTopicIdeas(source, format, language)
      .then((res) => {
        if (request.current === id) setIdeas({ format, text: source, status: 'done', ideas: res.ideas });
      })
      .catch((err: unknown) => {
        if (request.current === id) setIdeas({ format, text: source, status: 'error', ideas: [], error: getErrorMessage(err) });
      });
  };
  const closeIdeas = () => {
    request.current += 1;
    setIdeas(null);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    askAI();
  };

  const surprise = () => {
    const pool = (list.length ? list : topics).filter((t) => !isPicked(t));
    const topic = randomOf(pool);
    if (topic) onPick(topic, topics);
  };
  const changeCategory = (id: string) => {
    setCategory(id);
    setLimit(PAGE);
  };
  const clearQuery = () => {
    setQuery('');
    setLimit(PAGE);
    closeIdeas();
  };

  return (
    <div className="grid min-w-0 content-start gap-4">
      <h2 className="min-w-0 font-display text-[clamp(22px,2.4vw,28px)] font-bold tracking-[-0.025em]">{spec.trendingTitle}</h2>

      {/* Search and "write your own" in one field: Enter or the AI button turns the words into topics. */}
      <form className="flex gap-2" onSubmit={submit}>
        <label className="flex h-11 min-w-0 flex-1 items-center gap-2.5 rounded-field border border-line bg-surface px-3.5 text-muted focus-within:border-accent">
          <Search className="size-4 shrink-0" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setLimit(PAGE);
            }}
            maxLength={MAX_QUERY}
            enterKeyHint="go"
            placeholder="Search topics or write your own…"
            aria-label="Search topics or write your own"
            className="min-w-0 flex-1 bg-transparent text-sm text-text outline-none"
          />
          {query && (
            <button type="button" onClick={clearQuery} className="grid place-items-center text-muted hover:text-text cursor-pointer" aria-label="Clear search">
              <X className="size-[15px]" />
            </button>
          )}
        </label>
        {text ? (
          <button
            type="submit"
            disabled={!canAsk || asking}
            title={canAsk ? `AI turns your words into ${spec.show} topics` : 'Write a few words first'}
            aria-label={`Write ${spec.show} topics with AI`}
            className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-field bg-accent px-3 text-[13px] font-bold text-ink transition-colors hover:bg-accent-hover cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 sm:px-3.5"
          >
            {asking ? <Spinner className="size-[18px]" /> : <Sparkles className="size-[18px]" />}
            <span className="sm:hidden">AI</span>
            <span className="hidden sm:inline">AI topic</span>
          </button>
        ) : (
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
        )}
      </form>

      {ideasShown && <IdeasPanel ideas={ideasShown} show={spec.show} topic={topic} onUse={onUseText} onUnpick={onUnpick} onAgain={() => askAI(ideasShown.text)} onClose={closeIdeas} />}

      {/* A search without matches has nothing to sort into categories. */}
      {categories.length > 1 && all.length > 0 && (
        <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5 min-[1180px]:flex-wrap" role="tablist" aria-label="Categories">
          {[{ id: 'all', count: all.length }, ...categories.map((c) => ({ id: c.id, count: countIn(c.id) }))].map((c) => {
            const on = activeCategory === c.id;
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
      {data && topics.length === 0 && !searching && (
        <div className="rounded-[16px] border border-dashed border-line-2 p-7 text-center text-sm text-text-3">
          No {spec.trendingTitle.toLowerCase()} yet today — write your own topic above.
        </div>
      )}

      {shown.length > 0 && (
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,270px),1fr))]">
          {shown.map((t) => (
            <TopicCard key={t.id} topic={t} source={t.sources[0]} selected={isPicked(t)} badge={badges && t.rank <= HOT_BADGES} onPick={() => (isPicked(t) ? onUnpick() : onPick(t, topics))} />
          ))}
        </div>
      )}

      {shownEarlier.length > 0 && (
        <>
          <div className="flex items-center gap-2 pt-1 font-mono text-[11px] uppercase tracking-[0.08em] text-dim">
            <History className="size-3.5" /> Earlier topics <span className="text-dim/70">{earlierList.length}</span>
          </div>
          <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,270px),1fr))]">
            {shownEarlier.map((t) => (
              <TopicCard key={t.id} topic={t} source={t.sources[0]} selected={isPicked(t)} badge={false} onPick={() => (isPicked(t) ? onUnpick() : onPick(t, topics))} />
            ))}
          </div>
        </>
      )}

      {data && total === 0 && (searching || topics.length > 0) && (
        <div className="grid justify-items-center gap-2.5 rounded-[16px] border border-dashed border-line-2 p-7 text-center">
          <div className="text-sm text-text-3">
            {!searching ? 'No topics in this category today.' : archive.loading ? 'Searching earlier topics…' : `No topics match “${text}”.`}
          </div>
          {searching && !archive.loading && !ideasShown && (
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
              {canAsk && (
                <button type="button" onClick={() => askAI()} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent hover:text-accent-hover cursor-pointer">
                  <Sparkles className="size-3.5" /> Turn it into a topic with AI
                </button>
              )}
              <button type="button" onClick={() => onUseText(text.replace(/\??$/, '?'))} className="text-[13px] font-semibold text-text-3 hover:text-text cursor-pointer">
                Use my words as they are →
              </button>
            </div>
          )}
        </div>
      )}

      {total > limit && (
        <button
          type="button"
          onClick={() => setLimit((n) => n + PAGE)}
          className="inline-flex h-[42px] items-center gap-2 justify-self-center rounded-field border border-line-2 bg-surface px-5 text-[13px] font-semibold transition-colors hover:bg-surface-2 cursor-pointer"
        >
          Show more <span className="font-mono text-[11px] text-muted">{total - limit} left</span>
        </button>
      )}
    </div>
  );
};
