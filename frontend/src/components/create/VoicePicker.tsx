import { Check, Mic, Search, Wand2, X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import type { VoiceInfo } from '../../api/types';
import { PickerFace } from './PickerFace';
import { pickerTriggerClass, usePickerPopover } from './usePickerPopover';
import { useVoicePreview } from './useVoicePreview';
import { VoicePreviewButton } from './VoicePreviewButton';

interface VoicePickerProps {
  value: string;
  voices: VoiceInfo[];
  loading: boolean;
  /** No catalogue (premium list unavailable): the server assigns voices, nothing to pick. */
  auto: boolean;
  /** Speaker name per voice id already used by another speaker. */
  takenBy: Record<string, string>;
  /** Show the verified languages (ElevenLabs voices speak many; Edge voices one). */
  showLanguages: boolean;
  /** Debate language: ISO code (as in `VoiceInfo.languages`) and display name. */
  language: { code: string; name: string };
  /** Speaker colour (icon, open border). */
  color: string;
  onChange: (voiceId: string) => void;
}

const POPOVER_WIDTH = 460;
const POPOVER_HEIGHT = 440;

const matches = (voice: VoiceInfo, terms: string[]) => {
  const haystack = `${voice.name} ${voice.description ?? ''} ${voice.id}`.toLowerCase();
  return terms.every((t) => haystack.includes(t));
};

const genderOf = (voice: VoiceInfo) => voice.gender?.trim().toLowerCase() || '';
const termsOf = (query: string) => query.toLowerCase().split(/\s+/).filter(Boolean);

type Scope = 'native' | 'all';
const SCOPES: Scope[] = ['native', 'all'];
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Searchable voice list with gender filter, previews and "used by" hints. */
export const VoicePicker = ({ value, voices, loading, auto, takenBy, showLanguages, language, color, onChange }: VoicePickerProps) => {
  const { open, show: openPopover, close, placement, rootRef, triggerRef } = usePickerPopover(POPOVER_WIDTH, POPOVER_HEIGHT);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [scope, setScope] = useState<Scope>('native');
  const [active, setActive] = useState(value);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const preview = useVoicePreview();

  const selected = voices.find((v) => v.id === value);
  // Edge voices have no samples: no preview buttons at all rather than disabled ones.
  const hasPreviews = voices.some((v) => v.preview_url);
  // ElevenLabs voices are multilingual: offer the ones verified for the debate language first.
  const native = voices.filter((v) => language.code && v.languages.includes(language.code));
  const hasScope = showLanguages && native.length > 0 && native.length < voices.length;
  const pool = (s: Scope) => (hasScope && s === 'native' ? native : voices);
  const visibleFor = (q: string, f: string, s: Scope) => {
    const terms = termsOf(q);
    return pool(s).filter((v) => matches(v, terms) && (f === 'all' || genderOf(v) === f));
  };
  const genders = [...new Set(pool(scope).map(genderOf).filter(Boolean))].sort();
  const found = visibleFor(query, 'all', scope);
  const visible = visibleFor(query, filter, scope);

  // A new search or filter starts at the top of the list.
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = 0;
  }, [query, filter, scope]);

  // Bring the current choice into view when the list opens (without scrolling the page).
  useEffect(() => {
    if (!open) return;
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (list && row) list.scrollTop = row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2;
  }, [open]);

  const keepVisible = (id: string) => {
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>(`[data-voice="${CSS.escape(id)}"]`);
    if (!list || !row) return;
    if (row.offsetTop < list.scrollTop) list.scrollTop = row.offsetTop;
    else if (row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = row.offsetTop + row.offsetHeight - list.clientHeight;
  };

  const show = () => {
    setQuery('');
    setFilter('all');
    // Start with the native voices unless the current choice is not one of them.
    setScope(!value || native.some((v) => v.id === value) ? 'native' : 'all');
    setActive(value);
    openPopover();
  };

  const pick = (voice: VoiceInfo) => {
    onChange(voice.id);
    close();
  };

  const resetActive = (nextQuery: string, nextFilter: string, nextScope: Scope) => {
    setActive(visibleFor(nextQuery, nextFilter, nextScope)[0]?.id ?? '');
  };

  const changeScope = (next: Scope) => {
    setScope(next);
    setFilter('all');
    resetActive(query, 'all', next);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const voice = visible.find((v) => v.id === active);
      if (voice) pick(voice);
      return;
    }
    const moves: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 };
    if (!(e.key in moves) || visible.length === 0) return;
    e.preventDefault();
    const index = visible.findIndex((v) => v.id === active);
    const next = index < 0 ? 0 : Math.min(visible.length - 1, Math.max(0, index + moves[e.key]));
    setActive(visible[next].id);
    keepVisible(visible[next].id);
  };

  if (auto) {
    return (
      <div className="flex h-[54px] min-w-0 items-center gap-2.5 rounded-[13px] border border-dashed border-line-2 pr-3 pl-2 text-left">
        <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted">
          <Wand2 className="size-4" />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-text-3">Picked automatically</span>
          <span className="mt-px block truncate text-xs text-muted">A distinct voice for every speaker</span>
        </span>
      </div>
    );
  }

  const disabled = loading || voices.length === 0;

  return (
    <div ref={rootRef} className="relative min-w-0">
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
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label="Voice"
        className={pickerTriggerClass(open)}
        style={open ? { borderColor: color } : undefined}
      >
        <PickerFace
          icon={<Mic className="size-4" />}
          color={color}
          title={selected?.name ?? (loading ? 'Loading voices…' : voices.length === 0 ? 'Voices unavailable' : value || 'Default voice')}
          sub={selected ? (selected.description ?? selected.id) : undefined}
          open={open}
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
                  resetActive(e.target.value, filter, scope);
                }}
                placeholder={`Search ${pool(scope).length} voices…`}
                aria-label="Search voices"
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
                    resetActive('', filter, scope);
                  }}
                  className="rounded p-0.5 text-muted hover:text-text cursor-pointer"
                  aria-label="Clear search"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
            {(hasScope || genders.length > 1) && (
              <div className="mt-2 flex items-center gap-1 overflow-x-auto" role="tablist" aria-label="Filter voices">
                {hasScope &&
                  SCOPES.map((s) => (
                    <button
                      key={s}
                      type="button"
                      role="tab"
                      aria-selected={scope === s}
                      onClick={() => changeScope(s)}
                      title={s === 'native' ? `Voices verified for ${language.name}` : `Every voice; the others speak ${language.name} with an accent`}
                      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-[3px] text-[11px] font-semibold transition-colors cursor-pointer ${
                        scope === s ? 'border-accent text-accent' : 'border-line-2 text-muted hover:text-text'
                      }`}
                    >
                      {s === 'native' ? language.name : 'All languages'}
                      <span className={scope === s ? 'text-accent/60' : 'text-dim'}>{s === 'native' ? native.length : voices.length}</span>
                    </button>
                  ))}
                {hasScope && genders.length > 1 && <span className="mx-1 h-4 w-px shrink-0 bg-line-2" aria-hidden="true" />}
                {genders.length > 1 && ['all', ...genders].map((g) => (
                  <button
                    key={g}
                    type="button"
                    role="tab"
                    aria-selected={filter === g}
                    onClick={() => {
                      setFilter(g);
                      resetActive(query, g, scope);
                    }}
                    className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors cursor-pointer ${
                      filter === g ? 'bg-accent text-ink' : 'text-muted hover:bg-surface-3 hover:text-text'
                    }`}
                  >
                    {g === 'all' ? 'All' : capitalize(g)}
                    <span className={filter === g ? 'text-ink/60' : 'text-dim'}>{g === 'all' ? found.length : found.filter((v) => genderOf(v) === g).length}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div ref={listRef} id={listId} role="listbox" aria-label="Voices" className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
            {visible.length === 0 && <div className="px-4 py-8 text-center text-sm text-muted">No voices match your search.</div>}
            {visible.map((v) => {
              const isSelected = v.id === value;
              const usedBy = takenBy[v.id];
              return (
                <div
                  key={v.id}
                  id={`${listId}-${v.id}`}
                  data-voice={v.id}
                  role="option"
                  aria-selected={isSelected}
                  onPointerMove={() => active !== v.id && setActive(v.id)}
                  onClick={() => pick(v)}
                  title={v.id}
                  className={`mx-1.5 flex cursor-pointer items-center gap-2.5 rounded-[10px] px-2 py-2 ${active === v.id ? 'bg-surface-3' : ''}`}
                >
                  {hasPreviews ? (
                    <VoicePreviewButton url={v.preview_url} playing={Boolean(v.preview_url) && preview.playing === v.preview_url} onToggle={() => preview.toggle(v.preview_url)} size="sm" />
                  ) : (
                    <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-surface-3 text-muted">
                      <Mic className="size-3" />
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className={`truncate text-[13px] font-semibold ${isSelected ? 'text-accent' : 'text-text'}`}>{v.name}</span>
                      {usedBy && <span className="shrink-0 rounded bg-surface-3 px-1 py-px text-[9px] font-semibold text-muted">{usedBy}</span>}
                    </span>
                    {v.description && <span className="mt-0.5 block truncate text-[11px] text-muted">{v.description}</span>}
                  </span>
                  {showLanguages && v.languages.length > 0 && (
                    <span className="hidden shrink-0 font-mono text-[10px] uppercase text-dim sm:block" title={v.languages.join(', ')}>
                      {v.languages.slice(0, 3).join(' ')}
                      {v.languages.length > 3 ? ` +${v.languages.length - 3}` : ''}
                    </span>
                  )}
                  {isSelected && <Check className="size-3.5 shrink-0 text-accent" strokeWidth={2.5} />}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
