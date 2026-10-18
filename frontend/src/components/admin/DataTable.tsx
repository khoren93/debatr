import type { ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** The server's sort key; sortable columns get a button in the header. */
  sort?: string;
  align?: 'left' | 'right';
  className?: string;
}

export interface SortState {
  key: string;
  order: 'asc' | 'desc';
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** The row opens this console page (the first cell is its link, for the keyboard). */
  rowHref?: (row: T) => string;
  sort?: SortState;
  onSort?: (key: string) => void;
  empty?: ReactNode;
  /** Dims the rows while a new page loads (they stay on screen). */
  loading?: boolean;
  caption?: string;
}

const SortIcon = ({ state }: { state: 'asc' | 'desc' | null }) => {
  if (state === 'asc') return <ArrowUp className="size-3" />;
  if (state === 'desc') return <ArrowDown className="size-3" />;
  return <ChevronsUpDown className="size-3 opacity-50" />;
};

/** Dense table of the console: sortable headers, clickable rows, scrolls sideways inside its box. */
export function DataTable<T>({ columns, rows, rowKey, rowHref, sort, onSort, empty, loading = false, caption }: DataTableProps<T>) {
  const navigate = useNavigate();
  if (rows.length === 0) return <div className="px-4 py-8 text-center text-sm text-muted">{empty ?? 'Nothing here.'}</div>;
  return (
    // `relative`: screen-reader-only labels (absolute) stay inside the scrolling box.
    <div className="relative overflow-x-auto">
      <table className={`w-full text-[13px] transition-opacity ${loading ? 'opacity-60' : ''}`}>
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            {columns.map((col) => {
              const state = sort && col.sort && sort.key === col.sort ? sort.order : null;
              const right = col.align === 'right';
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={state === 'asc' ? 'ascending' : state === 'desc' ? 'descending' : undefined}
                  className={`whitespace-nowrap px-3 py-2.5 font-medium first:pl-4 last:pr-4 ${right ? 'text-right' : ''} ${col.className ?? ''}`}
                >
                  {col.sort && onSort ? (
                    <button
                      type="button"
                      onClick={() => onSort(col.sort as string)}
                      className={`inline-flex cursor-pointer items-center gap-1 hover:text-text ${state ? 'text-text-2' : ''} ${right ? 'flex-row-reverse' : ''}`}
                    >
                      {col.header}
                      <SortIcon state={state} />
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((row) => {
            const href = rowHref?.(row);
            return (
              <tr
                key={rowKey(row)}
                onClick={
                  href
                    ? (e) => {
                        // Links and buttons inside the row keep their own click.
                        if ((e.target as HTMLElement).closest('a,button')) return;
                        navigate(href);
                      }
                    : undefined
                }
                className={`border-b border-line/70 last:border-b-0 ${href ? 'cursor-pointer hover:bg-surface-2/60' : ''}`}
              >
                {columns.map((col, i) => (
                  <td key={col.key} className={`px-3 py-2.5 align-middle first:pl-4 last:pr-4 ${col.align === 'right' ? 'text-right' : ''} ${col.className ?? ''}`}>
                    {i === 0 && href ? (
                      <Link to={href} className="block min-w-0 outline-none focus-visible:underline">
                        {col.cell(row)}
                      </Link>
                    ) : (
                      col.cell(row)
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface PagerProps {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
  disabled?: boolean;
}

/** "51–100 of 312" with previous / next. */
export const Pager = ({ offset, limit, total, onChange, disabled = false }: PagerProps) => {
  if (total <= limit && offset === 0) return null;
  const last = Math.min(total, offset + limit);
  const button = 'cursor-pointer rounded-[9px] border border-line-2 bg-surface px-3 py-1.5 text-xs font-semibold hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40';
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 text-xs text-muted">
      <span className="tabular-nums">
        {total ? offset + 1 : 0}–{last} of {total.toLocaleString()}
      </span>
      <div className="flex gap-2">
        <button type="button" className={button} disabled={disabled || offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </button>
        <button type="button" className={button} disabled={disabled || last >= total} onClick={() => onChange(offset + limit)}>
          Next
        </button>
      </div>
    </div>
  );
};
