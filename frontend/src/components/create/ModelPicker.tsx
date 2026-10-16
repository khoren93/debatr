import { Check, ChevronDown, Lock, Search, Sparkles, Trophy, X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import type { ModelInfo } from '../../api/types';
import { formatContext } from '../../lib/format';
import { modelAuthor } from '../../lib/modelIcons';
import { ModelIcon } from '../ui';

interface ModelPickerProps {
  value: string;
  models: ModelInfo[];
  loading: boolean;
  /** Paid models cannot be picked: no own key and no credits. */
  paidLocked: boolean;
  /** Audience rank per model id (1 = best), from the leaderboard. */
  ranks: Record<string, number>;
  onChange: (modelId: string) => void;
}

type Filter = 'all' | 'free' | 'paid' | 'ranked';

/** Models added to OpenRouter in the last 45 days get a "New" badge. */
const NEW_SINCE = Date.now() / 1000 - 45 * 86_400;
const POPOVER_HEIGHT = 470;

/** "Anthropic: Claude Sonnet 4.5" -> provider "Anthropic", title "Claude Sonnet 4.5". */
const splitName = (model: Pick<ModelInfo, 'id' | 'name'>) => {
  const sep = model.name.indexOf(': ');
  if (sep > 0) return { provider: model.name.slice(0, sep), title: model.name.slice(sep + 2) };
  return { provider: modelAuthor(model.id) || 'OpenRouter', title: model.name };
};

const perMillion = (price: string) => {
  const n = parseFloat(price) * 1_000_000;
  if (!Number.isFinite(n) || n < 0) return 'varies';
  if (n === 0) return '$0';
  return `$${n >= 10 ? n.toFixed(0) : n.toFixed(2)}`;
};

/** OpenRouter descriptions are Markdown; show links as plain text. */
const plainDescription = (text: string) => text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*_`#]/g, '').trim();

const matches = (model: ModelInfo, terms: string[]) => {
  const haystack = `${model.name} ${model.id}`.toLowerCase();
  return terms.every((t) => haystack.includes(t));
};

const PriceBadge = ({ model }: { model: ModelInfo }) =>
  model.is_free ? (
    <span className="rounded-md bg-ok/12 px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-[0.04em] text-ok">FREE</span>
  ) : (
    <span className="font-mono text-[11px] text-text-3" title="Output price per 1M tokens">
      {perMillion(model.pricing.completion)}
      <span className="text-dim">/M</span>
    </span>
  );

/** Searchable OpenRouter model list with provider logos, prices, context and audience rank. */
export const ModelPicker = ({ value, models, loading, paidLocked, ranks, onChange }: ModelPickerProps) => {
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [active, setActive] = useState(value);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const selected = models.find((m) => m.id === value);
  const locked = (m: ModelInfo) => paidLocked && !m.is_free && m.id !== value;
  const hasRanks = Object.keys(ranks).length > 0;

  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const found = models.filter((m) => matches(m, terms));
  const counts = {
    all: found.length,
    free: found.filter((m) => m.is_free).length,
    paid: found.filter((m) => !m.is_free).length,
    ranked: found.filter((m) => ranks[m.id]).length,
  };
  const visible =
    filter === 'free'
      ? found.filter((m) => m.is_free)
      : filter === 'paid'
        ? found.filter((m) => !m.is_free)
        : filter === 'ranked'
          ? found.filter((m) => ranks[m.id]).sort((a, b) => ranks[a.id] - ranks[b.id])
          : found;
  const sections =
    filter === 'all'
      ? [
          { label: 'Free', items: visible.filter((m) => m.is_free) },
          { label: paidLocked ? 'Paid · needs credits or your own key' : 'Paid · output price per 1M tokens', items: visible.filter((m) => !m.is_free) },
        ].filter((s) => s.items.length > 0)
      : [{ label: '', items: visible }];
  const ordered = sections.flatMap((s) => s.items);
  const selectable = ordered.filter((m) => !locked(m));
  const preview = models.find((m) => m.id === active) ?? selected;

  // Close on a click outside the picker.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  // Bring the current choice into view when the list opens (without scrolling the page).
  useEffect(() => {
    if (!open) return;
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (list && row) list.scrollTop = row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2;
  }, [open]);

  const keepVisible = (id: string) => {
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>(`[data-model="${CSS.escape(id)}"]`);
    if (!list || !row) return;
    if (row.offsetTop < list.scrollTop + 30) list.scrollTop = row.offsetTop - 30;
    else if (row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = row.offsetTop + row.offsetHeight - list.clientHeight;
  };

  const show = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) setDropUp(window.innerHeight - rect.bottom < POPOVER_HEIGHT && rect.top > window.innerHeight - rect.bottom);
    setQuery('');
    setFilter('all');
    setActive(value);
    setOpen(true);
  };

  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  };

  const pick = (model: ModelInfo) => {
    if (locked(model)) return;
    onChange(model.id);
    close();
  };

  const resetActive = (nextQuery: string, nextFilter: Filter) => {
    const nextTerms = nextQuery.toLowerCase().split(/\s+/).filter(Boolean);
    const first = models.find(
      (m) => matches(m, nextTerms) && !locked(m) && (nextFilter === 'all' || (nextFilter === 'free' ? m.is_free : nextFilter === 'paid' ? !m.is_free : ranks[m.id])),
    );
    setActive(first?.id ?? '');
    if (listRef.current) listRef.current.scrollTop = 0;
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const model = selectable.find((m) => m.id === active);
      if (model) pick(model);
      return;
    }
    const moves: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 };
    if (!(e.key in moves) || selectable.length === 0) return;
    e.preventDefault();
    const index = selectable.findIndex((m) => m.id === active);
    const next = index < 0 ? 0 : Math.min(selectable.length - 1, Math.max(0, index + moves[e.key]));
    setActive(selectable[next].id);
    keepVisible(selectable[next].id);
  };

  const name = selected ? splitName(selected) : null;

  return (
    <div ref={rootRef} className="relative min-w-0 flex-1">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (open ? close(false) : show())}
        onKeyDown={(e) => {
          if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
            e.preventDefault();
            show();
          }
        }}
        disabled={loading && !value}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label="Model"
        className={`flex w-full items-center gap-3 rounded-field border bg-ink px-2.5 py-2 text-left transition-colors cursor-pointer disabled:cursor-wait disabled:opacity-60 ${
          open ? 'border-accent' : 'border-line-2 hover:border-line-3'
        }`}
      >
        <ModelIcon modelId={value} size={18} tile />
        <span className="min-w-0 flex-1">
          {name && selected ? (
            <>
              <span className="block truncate text-sm font-semibold text-text">{name.title}</span>
              <span className="mt-0.5 flex items-center gap-1.5 truncate text-[11px] text-muted">
                <span className="truncate">{name.provider}</span>
                <span className="text-dim">·</span>
                {selected.is_free ? <span className="font-semibold text-ok">Free</span> : <span className="font-mono">{perMillion(selected.pricing.completion)}/M out</span>}
                <span className="text-dim">·</span>
                <span className="font-mono">{formatContext(selected.context_length)} ctx</span>
              </span>
            </>
          ) : (
            <span className="block truncate py-2 text-sm text-muted">{value || (loading ? 'Loading models…' : 'Select a model')}</span>
          )}
        </span>
        <ChevronDown className={`size-4 shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          className={`absolute inset-x-0 z-40 flex max-h-[min(470px,70vh)] min-w-[min(300px,calc(100vw-32px))] flex-col overflow-hidden rounded-card border border-line-2 bg-surface-2 shadow-2xl shadow-black/60 animate-rise ${
            dropUp ? 'bottom-full mb-2' : 'top-full mt-2'
          }`}
          onKeyDown={onKeyDown}
        >
          <div className="border-b border-line p-2.5">
            <div className="flex items-center gap-2 rounded-[10px] border border-line-2 bg-ink px-2.5 focus-within:border-accent">
              <Search className="size-3.5 shrink-0 text-muted" />
              <input
                autoFocus
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  resetActive(e.target.value, filter);
                }}
                placeholder={`Search ${models.length} models…`}
                aria-label="Search models"
                aria-controls={listId}
                aria-activedescendant={active ? `${listId}-${active}` : undefined}
                role="combobox"
                aria-expanded
                className="min-w-0 flex-1 bg-transparent py-2 text-sm text-text outline-none placeholder:text-dim"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery('');
                    resetActive('', filter);
                  }}
                  className="rounded p-0.5 text-muted hover:text-text cursor-pointer"
                  aria-label="Clear search"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
            <div className="mt-2 flex gap-1 overflow-x-auto" role="tablist" aria-label="Filter models">
              {(['all', 'free', 'paid', ...(hasRanks ? (['ranked'] as const) : [])] as Filter[]).map((f) => (
                <button
                  key={f}
                  type="button"
                  role="tab"
                  aria-selected={filter === f}
                  onClick={() => {
                    setFilter(f);
                    resetActive(query, f);
                  }}
                  className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors cursor-pointer ${
                    filter === f ? 'bg-accent text-ink' : 'text-muted hover:bg-surface-3 hover:text-text'
                  }`}
                >
                  {f === 'ranked' && <Trophy className="size-3" />}
                  {{ all: 'All', free: 'Free', paid: 'Paid', ranked: 'Ranked' }[f]}
                  <span className={filter === f ? 'text-ink/60' : 'text-dim'}>{counts[f]}</span>
                </button>
              ))}
            </div>
          </div>

          <div ref={listRef} id={listId} role="listbox" aria-label="Models" className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
            {ordered.length === 0 && <div className="px-4 py-8 text-center text-sm text-muted">{loading ? 'Loading models…' : 'No models match your search.'}</div>}
            {sections.map((section) => (
              <div key={section.label || 'list'} role="group" aria-label={section.label || undefined}>
                {section.label && (
                  <div className="sticky top-0 z-10 flex items-center gap-1.5 bg-surface-2/95 px-3.5 pt-2 pb-1 font-mono text-[10px] uppercase tracking-[0.08em] text-dim backdrop-blur">
                    {section.label} <span className="text-dim/70">{section.items.length}</span>
                  </div>
                )}
                {section.items.map((m) => {
                  const { provider, title } = splitName(m);
                  const isSelected = m.id === value;
                  const isLocked = locked(m);
                  const rank = ranks[m.id];
                  return (
                    <div
                      key={m.id}
                      id={`${listId}-${m.id}`}
                      data-model={m.id}
                      role="option"
                      aria-selected={isSelected}
                      aria-disabled={isLocked}
                      onPointerMove={() => !isLocked && active !== m.id && setActive(m.id)}
                      onClick={() => pick(m)}
                      title={isLocked ? 'Paid model: add credits or use your own OpenRouter key' : m.id}
                      className={`mx-1.5 flex items-center gap-2.5 rounded-[10px] px-2 py-2 ${isLocked ? 'cursor-not-allowed opacity-45' : 'cursor-pointer'} ${
                        active === m.id && !isLocked ? 'bg-surface-3' : ''
                      }`}
                    >
                      <ModelIcon modelId={m.id} size={16} tile />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className={`truncate text-[13px] font-semibold ${isSelected ? 'text-accent' : 'text-text'}`}>{title}</span>
                          {m.created > NEW_SINCE && (
                            <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-violet/15 px-1 py-px text-[9px] font-bold uppercase tracking-[0.06em] text-violet">
                              <Sparkles className="size-2.5" /> New
                            </span>
                          )}
                        </span>
                        <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted">
                          <span className="truncate">{provider}</span>
                          <span className="text-dim">·</span>
                          <span className="shrink-0 font-mono">{formatContext(m.context_length)}</span>
                          {rank && (
                            <span className="inline-flex shrink-0 items-center gap-0.5 text-host" title="Audience ranking">
                              <Trophy className="size-2.5" />#{rank}
                            </span>
                          )}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1.5">
                        {isLocked ? <Lock className="size-3.5 text-muted" /> : <PriceBadge model={m} />}
                        {isSelected && <Check className="size-3.5 text-accent" strokeWidth={2.5} />}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          {preview && (
            <div className="border-t border-line bg-surface px-3.5 py-2.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[10px] text-muted">
                {preview.is_free ? (
                  <span className="text-ok">FREE</span>
                ) : (
                  <>
                    <span>
                      in <span className="text-text-3">{perMillion(preview.pricing.prompt)}</span>
                    </span>
                    <span>
                      out <span className="text-text-3">{perMillion(preview.pricing.completion)}</span>
                      <span className="text-dim"> /1M</span>
                    </span>
                  </>
                )}
                <span>
                  ctx <span className="text-text-3">{formatContext(preview.context_length)}</span>
                </span>
                <span className="min-w-0 truncate text-dim">{preview.id}</span>
              </div>
              {preview.description && <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-text-3">{plainDescription(preview.description)}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
