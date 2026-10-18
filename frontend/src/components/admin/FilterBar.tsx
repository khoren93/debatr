import { useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import { Button, Dropdown, Input } from '../ui';
import { pick, type FilterSpec } from './filters';

interface FilterBarProps {
  params: URLSearchParams;
  filters: FilterSpec[];
  searchLabel: string;
  searchPlaceholder: string;
  onChange: (changes: Record<string, string>) => void;
  onReset: () => void;
}

/** Search box (typing settles for 300 ms) and one dropdown per filter, all kept in the URL. */
export const FilterBar = ({ params, filters, searchLabel, searchPlaceholder, onChange, onReset }: FilterBarProps) => {
  const [text, setText] = useState(params.get('q') ?? '');
  const typing = useRef<number | undefined>(undefined);
  const filtered = filters.some((f) => pick(params, f)) || Boolean(params.get('q'));

  const search = (value: string) => {
    setText(value);
    window.clearTimeout(typing.current);
    typing.current = window.setTimeout(() => onChange({ q: value.trim() }), 300);
  };

  return (
    <div className="grid gap-3">
      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
        <Input value={text} onChange={(e) => search(e.target.value)} placeholder={searchPlaceholder} aria-label={searchLabel} className="pl-9" type="search" />
      </div>
      <div className="grid grid-cols-2 items-center gap-2 sm:flex sm:flex-wrap">
        {filters.map((f) => (
          <div key={f.key} className="min-w-0 sm:w-[190px]">
            <Dropdown size="sm" aria-label={f.label} value={pick(params, f)} options={f.options} onChange={(value) => onChange({ [f.key]: value })} />
          </div>
        ))}
        {filtered && (
          <Button
            variant="ghost"
            size="sm"
            icon={<X className="size-3.5" />}
            onClick={() => {
              setText('');
              onReset();
            }}
          >
            Reset
          </Button>
        )}
      </div>
    </div>
  );
};

/** A filter set from elsewhere (a card's link), shown as a removable chip under the bar. */
export const FilterChip = ({ label, onClear }: { label: string; onClear: () => void }) => (
  <span className="inline-flex items-center gap-1.5 rounded-full border border-line-2 bg-surface-2 py-1 pl-3 pr-1.5 text-xs text-text-2">
    {label}
    <button type="button" onClick={onClear} aria-label={`Clear ${label}`} className="cursor-pointer rounded-full p-0.5 text-muted hover:text-text">
      <X className="size-3.5" />
    </button>
  </span>
);
