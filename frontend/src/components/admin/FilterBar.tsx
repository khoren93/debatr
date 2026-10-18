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
