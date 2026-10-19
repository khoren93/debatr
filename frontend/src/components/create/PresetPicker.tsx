import { Check } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { PickerFace } from './PickerFace';
import { pickerTriggerClass, usePickerPopover } from './usePickerPopover';

export interface PresetOption {
  id: string;
  /** Title in the list and on the trigger. */
  full: string;
  /** One line under it. */
  short: string;
  /** Small mono tag on the right of the title (a flow's voice type). */
  badge?: string;
}

interface PresetPickerProps {
  value: string;
  options: PresetOption[];
  /** Tile icon of the trigger, in the speaker colour. */
  icon: ReactNode;
  /** Speaker colour for the trigger icon and the open border. */
  color: string;
  /** Names the field and the list ("Persona", "Flow"). */
  label: string;
  onPick: (id: string) => void;
}

const POPOVER_WIDTH = 380;
const POPOVER_HEIGHT = 420;

/** A short list of presets in a speaker-row field (personas, rappers' flows), keyboard-driven. */
export const PresetPicker = ({ value, options, icon, color, label, onPick }: PresetPickerProps) => {
  const { open, show: openPopover, close, placement, rootRef, triggerRef } = usePickerPopover(POPOVER_WIDTH, POPOVER_HEIGHT);
  const [active, setActive] = useState(value);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const current = options.find((o) => o.id === value);

  // Focus the list (for the arrow keys) and bring the current choice into view.
  useEffect(() => {
    if (!open) return;
    const list = listRef.current;
    list?.focus({ preventScroll: true });
    const row = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (list && row) list.scrollTop = row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2;
  }, [open]);

  const show = () => {
    setActive(value);
    openPopover();
  };

  const pick = (id: string) => {
    onPick(id);
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
      pick(active);
      return;
    }
    const moves: Record<string, number> = { ArrowDown: 1, ArrowUp: -1 };
    if (!(e.key in moves)) return;
    e.preventDefault();
    const index = options.findIndex((o) => o.id === active);
    const next = options[(index + moves[e.key] + options.length) % options.length];
    setActive(next.id);
    listRef.current?.querySelector<HTMLElement>(`[data-preset="${next.id}"]`)?.scrollIntoView({ block: 'nearest' });
  };

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
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={label}
        className={pickerTriggerClass(open)}
        style={open ? { borderColor: color } : undefined}
      >
        <PickerFace icon={icon} color={color} title={current?.full ?? value} sub={current?.short} open={open} />
      </button>

      {open && (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label={label}
          aria-activedescendant={`${listId}-${active}`}
          tabIndex={-1}
          onKeyDown={onKeyDown}
          className={`absolute z-40 overflow-y-auto overscroll-contain rounded-card border border-line-2 bg-surface-2 py-1.5 shadow-2xl shadow-black/60 outline-none animate-rise ${
            placement.dropUp ? 'bottom-full mb-2' : 'top-full mt-2'
          }`}
          style={{ left: placement.left, width: placement.width, maxHeight: placement.maxHeight }}
        >
          {options.map((o) => {
            const isSelected = o.id === value;
            return (
              <div
                key={o.id}
                id={`${listId}-${o.id}`}
                data-preset={o.id}
                role="option"
                aria-selected={isSelected}
                onPointerMove={() => active !== o.id && setActive(o.id)}
                onClick={() => pick(o.id)}
                className={`mx-1.5 flex cursor-pointer items-start gap-2.5 rounded-[10px] px-2.5 py-2 ${active === o.id ? 'bg-surface-3' : ''}`}
              >
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className={`text-[13px] font-semibold ${isSelected ? 'text-accent' : 'text-text'}`}>{o.full}</span>
                    {o.badge && <span className="font-mono text-[10px] tracking-[0.06em] text-dim">{o.badge}</span>}
                  </span>
                  <span className="mt-0.5 line-clamp-2 block text-[11px] leading-[1.4] text-muted">{o.short}</span>
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
