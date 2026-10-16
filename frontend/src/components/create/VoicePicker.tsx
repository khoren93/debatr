import { Check, ChevronDown, Mic, Play, Search, Square, Wand2, X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import type { VoiceInfo } from '../../api/types';
import { usePickerPopover } from './usePickerPopover';

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
  onChange: (voiceId: string) => void;
}

const POPOVER_WIDTH = 460;
const POPOVER_HEIGHT = 440;

const matches = (voice: VoiceInfo, terms: string[]) => {
  const haystack = `${voice.name} ${voice.description ?? ''} ${voice.id}`.toLowerCase();
  return terms.every((t) => haystack.includes(t));
};

const genderOf = (voice: VoiceInfo) => voice.gender?.trim().toLowerCase() || '';
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Only one preview plays at a time across all pickers. */
let currentPreview: HTMLAudioElement | null = null;

/** Plays voice samples; `playing` is the URL being played. */
const usePreview = () => {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);

  useEffect(
    () => () => {
      audioRef.current?.pause();
    },
    [],
  );

  const stop = () => {
    audioRef.current?.pause();
    audioRef.current = null;
    setPlaying(null);
  };

  const toggle = (url: string | null) => {
    if (!url) return;
    if (playing === url) {
      stop();
      return;
    }
    currentPreview?.pause();
    audioRef.current?.pause();
    const audio = new Audio(url);
    const ended = () => setPlaying((p) => (p === url ? null : p));
    audio.onpause = ended;
    audio.onended = ended;
    audio.onerror = ended;
    audioRef.current = audio;
    currentPreview = audio;
    audio
      .play()
      .then(() => setPlaying(url))
      .catch(ended);
  };

  return { playing, toggle };
};

const PreviewButton = ({ url, playing, onToggle, size = 'md' }: { url: string | null; playing: boolean; onToggle: () => void; size?: 'sm' | 'md' }) => (
  <button
    type="button"
    onClick={(e) => {
      e.stopPropagation();
      onToggle();
    }}
    disabled={!url}
    title={url ? (playing ? 'Stop preview' : 'Preview voice') : 'No preview for this voice'}
    aria-label={playing ? 'Stop preview' : 'Preview voice'}
    className={`grid shrink-0 place-items-center border transition-colors ${size === 'sm' ? 'size-7 rounded-lg' : 'size-10 rounded-[11px]'} ${
      url ? 'cursor-pointer border-line-2 bg-surface-2 text-text hover:border-accent' : 'cursor-not-allowed border-line bg-surface-2 text-dim'
    } ${playing ? 'border-accent text-accent' : ''}`}
  >
    {playing ? <Square className={size === 'sm' ? 'size-2.5' : 'size-3.5'} fill="currentColor" /> : <Play className={size === 'sm' ? 'size-2.5' : 'size-3.5'} fill="currentColor" />}
  </button>
);

/** Searchable voice list with gender filter, previews and "used by" hints. */
export const VoicePicker = ({ value, voices, loading, auto, takenBy, showLanguages, onChange }: VoicePickerProps) => {
  const { open, show: openPopover, close, placement, rootRef, triggerRef } = usePickerPopover(POPOVER_WIDTH, POPOVER_HEIGHT);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [active, setActive] = useState(value);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const preview = usePreview();

  const selected = voices.find((v) => v.id === value);
  // Edge voices have no samples: no preview buttons at all rather than disabled ones.
  const hasPreviews = voices.some((v) => v.preview_url);
  const genders = [...new Set(voices.map(genderOf).filter(Boolean))].sort();
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const found = voices.filter((v) => matches(v, terms));
  const visible = filter === 'all' ? found : found.filter((v) => genderOf(v) === filter);

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
    setActive(value);
    openPopover();
  };

  const pick = (voice: VoiceInfo) => {
    onChange(voice.id);
    close();
  };

  const resetActive = (nextQuery: string, nextFilter: string) => {
    const nextTerms = nextQuery.toLowerCase().split(/\s+/).filter(Boolean);
    const first = voices.find((v) => matches(v, nextTerms) && (nextFilter === 'all' || genderOf(v) === nextFilter));
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
      <div className="flex min-w-0 flex-1 items-center gap-3 rounded-field border border-dashed border-line-2 px-2.5 py-2 text-left">
        <span className="grid size-[30px] shrink-0 place-items-center rounded-lg bg-surface-2 text-muted">
          <Wand2 className="size-3.5" />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-text-3">Picked automatically</span>
          <span className="mt-0.5 block truncate text-[11px] text-muted">A distinct voice for every speaker</span>
        </span>
      </div>
    );
  }

  const disabled = loading || voices.length === 0;

  return (
    <div ref={rootRef} className="relative flex min-w-0 flex-1 items-center gap-2">
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
        className={`flex min-w-0 flex-1 items-center gap-3 rounded-field border bg-ink px-2.5 py-2 text-left transition-colors cursor-pointer disabled:cursor-wait disabled:opacity-60 ${
          open ? 'border-accent' : 'border-line-2 hover:border-line-3'
        }`}
      >
        <span className="grid size-[30px] shrink-0 place-items-center rounded-lg bg-surface-2 text-text-3">
          <Mic className="size-3.5" />
        </span>
        <span className="min-w-0 flex-1">
          {selected ? (
            <>
              <span className="block truncate text-sm font-semibold text-text">{selected.name}</span>
              <span className="mt-0.5 block truncate text-[11px] text-muted">{selected.description ?? selected.id}</span>
            </>
          ) : (
            <span className="block truncate py-2 text-sm text-muted">{loading ? 'Loading voices…' : voices.length === 0 ? 'Voices unavailable' : value || 'Default voice'}</span>
          )}
        </span>
        <ChevronDown className={`size-4 shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {hasPreviews && (
        <PreviewButton url={selected?.preview_url ?? null} playing={Boolean(selected?.preview_url) && preview.playing === selected?.preview_url} onToggle={() => preview.toggle(selected?.preview_url ?? null)} />
      )}

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
                placeholder={`Search ${voices.length} voices…`}
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
                    resetActive('', filter);
                  }}
                  className="rounded p-0.5 text-muted hover:text-text cursor-pointer"
                  aria-label="Clear search"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
            {genders.length > 1 && (
              <div className="mt-2 flex gap-1 overflow-x-auto" role="tablist" aria-label="Filter voices">
                {['all', ...genders].map((g) => (
                  <button
                    key={g}
                    type="button"
                    role="tab"
                    aria-selected={filter === g}
                    onClick={() => {
                      setFilter(g);
                      resetActive(query, g);
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
                    <PreviewButton url={v.preview_url} playing={Boolean(v.preview_url) && preview.playing === v.preview_url} onToggle={() => preview.toggle(v.preview_url)} size="sm" />
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
