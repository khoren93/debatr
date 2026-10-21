import { Check, ChevronDown } from 'lucide-react';
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export interface DropdownOption<T extends string | number> {
  value: T;
  label: ReactNode;
  /** Plain text for type-ahead when the label is not a string. */
  text?: string;
  /** Second line in the list (voice description, price…). */
  hint?: ReactNode;
  /** Shown at the row's end in the list only (a count…). */
  aside?: ReactNode;
  disabled?: boolean;
}

interface DropdownProps<T extends string | number> {
  value: T;
  options: DropdownOption<T>[];
  onChange: (value: T) => void;
  'aria-label'?: string;
  id?: string;
  disabled?: boolean;
  /** Trigger text when the value matches no option. */
  placeholder?: ReactNode;
  /** Before the trigger's text. */
  icon?: ReactNode;
  size?: 'xs' | 'sm' | 'md';
  className?: string;
  /** The list may be wider than the trigger (long voice names). */
  menuWidth?: number;
}

interface MenuPosition {
  top?: number;
  bottom?: number;
  left: number;
  width: number;
  maxHeight: number;
}

const GUTTER = 8;
const MAX_HEIGHT = 320;

/** Below the trigger, or above it when there is more room there; always inside the viewport. */
const menuPosition = (trigger: HTMLElement | null, count: number, menuWidth: number): MenuPosition | null => {
  const rect = trigger?.getBoundingClientRect();
  if (!rect) return null;
  const viewport = document.documentElement.clientWidth;
  const width = Math.min(Math.max(rect.width, menuWidth), viewport - 2 * GUTTER);
  const left = Math.min(Math.max(GUTTER, rect.left), viewport - GUTTER - width);
  const below = window.innerHeight - rect.bottom - GUTTER;
  const above = rect.top - GUTTER;
  const wanted = Math.min(MAX_HEIGHT, count * 40 + 14);
  if (below >= wanted || below >= above) return { top: rect.bottom + 6, left, width, maxHeight: Math.max(120, Math.min(MAX_HEIGHT, below - 6)) };
  return { bottom: window.innerHeight - rect.top + 6, left, width, maxHeight: Math.max(120, Math.min(MAX_HEIGHT, above - 6)) };
};

const SIZES = {
  xs: 'h-7 gap-1.5 rounded-md px-2 text-xs',
  sm: 'h-9 gap-2 rounded-[10px] px-2.5 text-[13px]',
  md: 'h-11 gap-2 rounded-field px-3 text-sm font-medium',
};

const optionText = <T extends string | number>(o: DropdownOption<T>) => (o.text ?? (typeof o.label === 'string' ? o.label : String(o.value))).toLowerCase();

/**
 * Select replacement in the studio style: no native popup. The list is portalled with fixed
 * positioning (modals scroll and would clip it), follows the trigger on scroll and supports
 * the arrow keys, Home / End, Enter / Space, Escape and type-ahead.
 */
export function Dropdown<T extends string | number>({
  value,
  options,
  onChange,
  id,
  disabled = false,
  placeholder = 'Select…',
  icon,
  size = 'md',
  className = '',
  menuWidth = 0,
  'aria-label': ariaLabel,
}: DropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<T>(value);
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const typed = useRef({ text: '', at: 0 });
  const listId = useId();
  const selected = options.find((o) => o.value === value);
  const enabled = options.filter((o) => !o.disabled);
  const optionId = (v: T) => `${listId}-${String(v).replace(/[^\w-]/g, '_')}`;

  // While open: follow the trigger (page or modal scroll, resize) and close on a click outside.
  useEffect(() => {
    if (!open) return;
    const follow = () => setPosition(menuPosition(triggerRef.current, options.length, menuWidth));
    const onPointer = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!triggerRef.current?.contains(target) && !listRef.current?.contains(target)) setOpen(false);
    };
    window.addEventListener('scroll', follow, true);
    window.addEventListener('resize', follow);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      window.removeEventListener('scroll', follow, true);
      window.removeEventListener('resize', follow);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open, options.length, menuWidth]);

  // Keyboard focus moves into the list; the current choice is scrolled into view.
  useEffect(() => {
    if (!open) return;
    const list = listRef.current;
    list?.focus({ preventScroll: true });
    const row = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (list && row) list.scrollTop = row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2;
  }, [open]);

  const show = () => {
    if (disabled) return;
    setActive(selected && !selected.disabled ? value : (enabled[0]?.value ?? value));
    setPosition(menuPosition(triggerRef.current, options.length, menuWidth));
    setOpen(true);
  };

  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  };

  const pick = (option: DropdownOption<T>) => {
    if (option.disabled) return;
    if (option.value !== value) onChange(option.value);
    close();
  };

  const moveTo = (option: DropdownOption<T> | undefined) => {
    if (!option) return;
    setActive(option.value);
    document.getElementById(optionId(option.value))?.scrollIntoView({ block: 'nearest' });
  };

  const onListKey = (e: KeyboardEvent) => {
    const index = enabled.findIndex((o) => o.value === active);
    switch (e.key) {
      case 'Escape':
        // Keep the surrounding modal open.
        e.preventDefault();
        e.stopPropagation();
        close();
        return;
      case 'Tab':
        close(false);
        return;
      case 'Enter':
      case ' ': {
        e.preventDefault();
        const option = enabled.find((o) => o.value === active);
        if (option) pick(option);
        return;
      }
      case 'ArrowDown':
        e.preventDefault();
        moveTo(enabled[Math.min(enabled.length - 1, index + 1)]);
        return;
      case 'ArrowUp':
        e.preventDefault();
        moveTo(enabled[Math.max(0, index - 1)]);
        return;
      case 'Home':
        e.preventDefault();
        moveTo(enabled[0]);
        return;
      case 'End':
        e.preventDefault();
        moveTo(enabled[enabled.length - 1]);
        return;
    }
    if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) {
      const at = e.timeStamp;
      typed.current = { text: (at - typed.current.at < 700 ? typed.current.text : '') + e.key.toLowerCase(), at };
      moveTo(enabled.find((o) => optionText(o).startsWith(typed.current.text)));
    }
  };

  return (
    <>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        disabled={disabled}
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
        aria-label={ariaLabel}
        className={`flex w-full min-w-0 items-center border bg-ink text-left text-text outline-none transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 focus-visible:border-accent ${SIZES[size]} ${
          open ? 'border-accent' : 'border-line-2 enabled:hover:border-line-3'
        } ${className}`}
      >
        {icon && <span className="flex shrink-0 text-muted">{icon}</span>}
        <span className={`min-w-0 flex-1 truncate ${selected ? '' : 'text-dim'}`}>{selected?.label ?? placeholder}</span>
        <ChevronDown className={`shrink-0 text-muted transition-transform duration-200 ${size === 'xs' ? 'size-3' : 'size-3.5'} ${open ? 'rotate-180' : ''}`} strokeWidth={2.5} />
      </button>
      {open &&
        position &&
        createPortal(
          <div
            ref={listRef}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-label={ariaLabel}
            aria-activedescendant={optionId(active)}
            onKeyDown={onListKey}
            className="fixed z-[70] grid grid-cols-1 content-start gap-0.5 overflow-y-auto overscroll-contain rounded-[14px] border border-white/10 bg-surface-2 p-1.5 shadow-[0_30px_60px_-20px_rgba(0,0,0,0.85)] outline-none animate-rise"
            style={{ top: position.top, bottom: position.bottom, left: position.left, width: position.width, maxHeight: position.maxHeight }}
          >
            {options.map((o) => {
              const isSelected = o.value === value;
              return (
                <div
                  key={String(o.value)}
                  id={optionId(o.value)}
                  role="option"
                  aria-selected={isSelected}
                  aria-disabled={o.disabled || undefined}
                  onPointerMove={() => !o.disabled && active !== o.value && setActive(o.value)}
                  onClick={() => pick(o)}
                  className={`flex items-center gap-2.5 rounded-[10px] px-2.5 py-2 ${o.disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer'} ${active === o.value && !o.disabled ? 'bg-surface-4' : ''}`}
                >
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate text-[13px] font-semibold ${isSelected ? 'text-accent' : 'text-text'}`}>{o.label}</span>
                    {o.hint && <span className="mt-px block truncate text-[11.5px] text-muted">{o.hint}</span>}
                  </span>
                  {o.aside !== undefined && <span className="shrink-0 font-mono text-[11px] text-muted">{o.aside}</span>}
                  <span className="grid w-4 shrink-0 place-items-center text-accent">{isSelected && <Check className="size-3.5" strokeWidth={2.5} />}</span>
                </div>
              );
            })}
          </div>,
          document.body,
        )}
    </>
  );
}
