import { Check, ChevronDown, Drama } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { STYLE_PRESETS, type PersonaStyle } from '../../data/styles';
import { usePickerPopover } from './usePickerPopover';

interface PersonaPickerProps {
  /** Preset the system prompt currently uses; null = custom prompt. */
  value: PersonaStyle | null;
  /** Speaker colour for the trigger icon. */
  color: string;
  onChange: (style: PersonaStyle) => void;
}

const POPOVER_WIDTH = 380;
const POPOVER_HEIGHT = 420;

/** Persona preset dropdown: replaces the "Style: …" line of the speaker's system prompt. */
export const PersonaPicker = ({ value, color, onChange }: PersonaPickerProps) => {
  const { open, show: openPopover, close, placement, rootRef, triggerRef } = usePickerPopover(POPOVER_WIDTH, POPOVER_HEIGHT);
  const [active, setActive] = useState(value?.id ?? STYLE_PRESETS[0].id);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  // Focus the list (for the arrow keys) and bring the current choice into view.
  useEffect(() => {
    if (!open) return;
    const list = listRef.current;
    list?.focus({ preventScroll: true });
    const row = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (list && row) list.scrollTop = row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2;
  }, [open]);

  const show = () => {
    setActive(value?.id ?? STYLE_PRESETS[0].id);
    openPopover();
  };

  const pick = (style: PersonaStyle) => {
    onChange(style);
    close();
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape' || e.key === 'Tab') {
      if (e.key === 'Escape') e.preventDefault();
      close(e.key === 'Escape');
      return;
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      const style = STYLE_PRESETS.find((s) => s.id === active);
      if (style) pick(style);
      return;
    }
    const moves: Record<string, number> = { ArrowDown: 1, ArrowUp: -1 };
    if (!(e.key in moves)) return;
    e.preventDefault();
    const index = STYLE_PRESETS.findIndex((s) => s.id === active);
    const next = STYLE_PRESETS[(index + moves[e.key] + STYLE_PRESETS.length) % STYLE_PRESETS.length];
    setActive(next.id);
    listRef.current?.querySelector<HTMLElement>(`[data-style="${next.id}"]`)?.scrollIntoView({ block: 'nearest' });
  };

  return (
    <div ref={rootRef} className="relative flex min-w-0 flex-1">
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
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label="Persona"
        className={`flex min-w-0 flex-1 items-center gap-3 rounded-field border bg-ink px-2.5 py-2 text-left transition-colors cursor-pointer ${
          open ? 'border-accent' : 'border-line-2 hover:border-line-3'
        }`}
      >
        <span className="grid size-[30px] shrink-0 place-items-center rounded-lg bg-surface-2" style={{ color }}>
          <Drama className="size-3.5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-text">{value?.full ?? 'Custom'}</span>
          <span className="mt-0.5 block truncate text-[11px] text-muted">{value?.desc ?? 'Your own system prompt'}</span>
        </span>
        <ChevronDown className={`size-4 shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Personas"
          aria-activedescendant={`${listId}-${active}`}
          tabIndex={-1}
          onKeyDown={onKeyDown}
          className={`absolute z-40 overflow-y-auto overscroll-contain rounded-card border border-line-2 bg-surface-2 py-1.5 shadow-2xl shadow-black/60 outline-none animate-rise ${
            placement.dropUp ? 'bottom-full mb-2' : 'top-full mt-2'
          }`}
          style={{ left: placement.left, width: placement.width, maxHeight: placement.maxHeight }}
        >
          {STYLE_PRESETS.map((s) => {
            const isSelected = s.id === value?.id;
            return (
              <div
                key={s.id}
                id={`${listId}-${s.id}`}
                data-style={s.id}
                role="option"
                aria-selected={isSelected}
                onPointerMove={() => active !== s.id && setActive(s.id)}
                onClick={() => pick(s)}
                className={`mx-1.5 flex cursor-pointer items-start gap-2.5 rounded-[10px] px-2.5 py-2 ${active === s.id ? 'bg-surface-3' : ''}`}
              >
                <span className="min-w-0 flex-1">
                  <span className={`block text-[13px] font-semibold ${isSelected ? 'text-accent' : 'text-text'}`}>{s.full}</span>
                  <span className="mt-0.5 line-clamp-2 block text-[11px] leading-[1.4] text-muted">{s.desc}</span>
                </span>
                {isSelected && <Check className="mt-0.5 size-3.5 shrink-0 text-accent" strokeWidth={2.5} />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
