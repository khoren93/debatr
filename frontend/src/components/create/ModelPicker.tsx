import { Check, Lock, Search, Sparkles, Trophy, X, Zap } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import type { ModelInfo } from '../../api/types';
import { formatContext } from '../../lib/format';
import { FREE_ROUTER_ID, perMillion, splitModelName as splitName } from '../../lib/modelNames';
import { ModelIcon } from '../ui';
import { PickerFace } from './PickerFace';
import { pickerTriggerClass, usePickerPopover } from './usePickerPopover';

interface ModelPickerProps {
  value: string;
  models: ModelInfo[];
  loading: boolean;
  /** Paid models cannot be picked: no own key and no credits. */
  paidLocked: boolean;
  /** Audience rank per model id (1 = best), from the leaderboard. */
  ranks: Record<string, number>;
  /** Speaker colour, role chip and on-stage name (named after the model) for the trigger. */
  color: string;
  tag: string;
  speakerName: string;
  onChange: (modelId: string) => void;
}

type Filter = 'all' | 'free' | 'paid' | 'latest';

const FILTER_LABELS: Record<Filter, string> = { all: 'All', free: 'Free', paid: 'Paid', latest: 'Latest' };

/** Models added to OpenRouter in the last 45 days get a "New" badge. */
const NEW_SINCE = Date.now() / 1000 - 45 * 86_400;
const POPOVER_WIDTH = 580;
const POPOVER_HEIGHT = 470;

/** OpenRouter descriptions are Markdown; show links as plain text. */
const plainDescription = (text: string) => text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*_`#]/g, '').trim();

const matches = (model: ModelInfo, terms: string[]) => {
  const haystack = `${model.name} ${model.id}`.toLowerCase();
  return terms.every((t) => haystack.includes(t));
};

/** OpenRouter aliases that always point at a provider's newest version ("~openai/gpt-latest"). */
const isLatest = (model: ModelInfo) => /latest/i.test(`${model.id} ${model.name}`);

const inFilter = (model: ModelInfo, filter: Filter) =>
  filter === 'all' || (filter === 'free' ? model.is_free : filter === 'paid' ? !model.is_free : isLatest(model));

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
export const ModelPicker = ({ value, models, loading, paidLocked, ranks, color, tag, speakerName, onChange }: ModelPickerProps) => {
  const { open, show: openPopover, close, placement, rootRef, triggerRef } = usePickerPopover(POPOVER_WIDTH, POPOVER_HEIGHT);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [active, setActive] = useState(value);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const selected = models.find((m) => m.id === value);
  const locked = (m: ModelInfo) => paidLocked && !m.is_free && m.id !== value;
  const hasLatest = models.some(isLatest);

  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  // The free router (the default model) leads the list.
  const sorted = [...models].sort((a, b) => Number(b.id === FREE_ROUTER_ID) - Number(a.id === FREE_ROUTER_ID));
  const found = sorted.filter((m) => matches(m, terms));
  const counts = {
    all: found.length,
    free: found.filter((m) => m.is_free).length,
    paid: found.filter((m) => !m.is_free).length,
    latest: found.filter(isLatest).length,
  };
  const visible = found.filter((m) => inFilter(m, filter));
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
    setQuery('');
    setFilter('all');
    setActive(value);
    openPopover();
  };

  const pick = (model: ModelInfo) => {
    if (locked(model)) return;
    onChange(model.id);
    close();
  };

  const resetActive = (nextQuery: string, nextFilter: Filter) => {
    const nextTerms = nextQuery.toLowerCase().split(/\s+/).filter(Boolean);
    const first = sorted.find((m) => matches(m, nextTerms) && !locked(m) && inFilter(m, nextFilter));
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
        aria-label={`Model of ${speakerName}`}
        className={pickerTriggerClass(open)}
        style={open ? { borderColor: color } : undefined}
      >
        <PickerFace
          icon={<ModelIcon modelId={value} size={21} className="text-text" />}
          color={color}
          outlined
          tag={tag}
          title={speakerName}
          open={open}
          sub={
            name && selected ? (
              <>
                {name.title} · {selected.is_free ? 'Free' : `${perMillion(selected.pricing.completion)}/M`} · {formatContext(selected.context_length)} ctx
                {ranks[selected.id] && (
                  <span className="text-host" title="Audience ranking">
                    {' '}
                    · <Trophy className="inline size-2.5 align-[-1px]" />#{ranks[selected.id]}
                  </span>
                )}
              </>
            ) : (
              value || (loading ? 'Loading models…' : 'Select a model')
            )
          }
        />
      </button>

      {open && (
        <div
          className={`absolute z-40 flex flex-col overflow-hidden rounded-card border border-line-2 bg-surface-2 shadow-2xl shadow-black/60 animate-rise ${
            placement.dropUp ? 'bottom-full mb-2' : 'top-full mt-2'
          }`}
          style={{ left: placement.left, width: placement.width, maxHeight: placement.maxHeight }}
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
              {(['all', 'free', 'paid', ...(hasLatest ? (['latest'] as const) : [])] as Filter[]).map((f) => (
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
                  {f === 'latest' && <Zap className="size-3" />}
                  {FILTER_LABELS[f]}
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
                      title={isLocked ? 'Paid model: add credits or your own OpenRouter key in Account' : m.id}
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

          {/* Details footer only when there is room for the list as well. */}
          {preview && placement.maxHeight >= 400 && (
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
