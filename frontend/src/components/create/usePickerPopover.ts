import { useEffect, useRef, useState } from 'react';

export interface PopoverPlacement {
  dropUp: boolean;
  /** Offset from the trigger's left edge (negative = shifted left to stay on screen). */
  left: number;
  width: number;
  maxHeight: number;
}

const GUTTER = 16;

/** Height of the mobile top bar / bottom tabs (AppShell `data-bar`), 0 when hidden. */
const barHeight = (edge: 'top' | 'bottom') => document.querySelector(`[data-bar="${edge}"]`)?.getBoundingClientRect().height ?? 0;

/**
 * Open state and placement of the wizard's searchable pickers (models, voices). The popover is
 * wider than the speaker card: it starts at the trigger's left edge, moves left when it would
 * leave the viewport and opens upwards when there is no room below.
 */
export const usePickerPopover = (width: number, height: number) => {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<PopoverPlacement>({ dropUp: false, left: 0, width, maxHeight: height });
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Close on a click outside the picker.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  const show = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      const viewport = document.documentElement.clientWidth;
      const w = Math.max(rect.width, Math.min(width, viewport - 2 * GUTTER));
      const left = Math.max(GUTTER - rect.left, Math.min(0, viewport - GUTTER - rect.left - w));
      // The step's animation makes a stacking context, so the popover cannot rise above the
      // mobile bars: fit it into the space between them instead.
      const below = window.innerHeight - barHeight('bottom') - rect.bottom - GUTTER;
      const above = rect.top - barHeight('top') - GUTTER;
      const dropUp = below < height && above > below;
      setPlacement({ dropUp, left, width: w, maxHeight: Math.max(220, Math.min(height, dropUp ? above : below)) });
    }
    setOpen(true);
  };

  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  };

  return { open, show, close, placement, rootRef, triggerRef };
};

/** Trigger button of a speaker-row field (54px, the design's model / voice / persona boxes). */
export const pickerTriggerClass = (open: boolean) =>
  `flex h-[54px] w-full min-w-0 items-center gap-2.5 rounded-[13px] border bg-ink pr-3 pl-2 text-left transition-colors cursor-pointer disabled:cursor-wait disabled:opacity-60 ${
    open ? '' : 'border-white/10 hover:border-white/22'
  }`;
