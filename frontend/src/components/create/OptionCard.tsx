import { Check } from 'lucide-react';
import type { ReactNode } from 'react';

interface OptionCardProps {
  active: boolean;
  onClick: () => void;
  title: ReactNode;
  text?: ReactNode;
  /** Right-aligned slot in the title row (price tag). */
  right?: ReactNode;
  /** Leading icon block (outputs). */
  leading?: ReactNode;
  /** Render a check box (multi-select cards). */
  checkbox?: boolean;
  disabled?: boolean;
  title_?: string;
}

/** Selectable card used for writing style and outputs. */
export const OptionCard = ({ active, onClick, title, text, right, leading, checkbox = false, disabled = false, title_ }: OptionCardProps) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    aria-pressed={active}
    title={title_}
    className={`flex w-full items-center gap-3.5 rounded-[14px] border p-4 text-left transition-colors ${
      active ? 'border-accent bg-accent/6' : 'border-line-2 bg-ink hover:border-line-3'
    } ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}
  >
    {leading}
    <div className="min-w-0 flex-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-bold">{title}</span>
        {right}
      </div>
      {text && <div className="mt-1 text-xs leading-[1.45] text-muted">{text}</div>}
    </div>
    {checkbox && (
      <span
        className={`grid size-5 shrink-0 place-items-center rounded-md border ${active ? 'border-accent bg-accent text-ink' : 'border-line-3 bg-transparent'}`}
        aria-hidden="true"
      >
        {active && <Check className="size-3" strokeWidth={3.5} />}
      </span>
    )}
  </button>
);
