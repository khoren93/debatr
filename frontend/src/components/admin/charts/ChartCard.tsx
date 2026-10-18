import { useState, type ReactNode } from 'react';
import { Table2, BarChart3 } from 'lucide-react';
import { Card } from '../../ui';

export interface LegendEntry {
  label: string;
  color: string;
  shape: 'line' | 'square';
}

export interface TableColumn {
  label: string;
  values: string[];
}

interface ChartCardProps {
  title: string;
  subtitle?: ReactNode;
  legend?: LegendEntry[];
  /** The same numbers as a table (the accessible twin of the chart). */
  table: { rowLabels: string[]; columns: TableColumn[] };
  children: ReactNode;
}

/** A chart with its title, legend and a switch to the table view. */
export const ChartCard = ({ title, subtitle, legend, table, children }: ChartCardProps) => {
  const [asTable, setAsTable] = useState(false);
  return (
    <Card padding="sm" className="min-w-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text-2">{title}</h3>
          {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
        </div>
        <button
          type="button"
          onClick={() => setAsTable((v) => !v)}
          className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted hover:bg-surface-2 hover:text-text"
          aria-pressed={asTable}
        >
          {asTable ? <BarChart3 className="size-3.5" /> : <Table2 className="size-3.5" />}
          {asTable ? 'Chart' : 'Table'}
        </button>
      </div>
      {legend && legend.length > 1 && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {legend.map((entry) => (
            <li key={entry.label} className="flex items-center gap-1.5 text-xs text-text-3">
              <span
                aria-hidden
                className={entry.shape === 'square' ? 'size-2.5 rounded-[3px]' : 'h-0.5 w-3.5 rounded-full'}
                style={{ background: entry.color }}
              />
              {entry.label}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3">
        {asTable ? (
          <div className="max-h-72 overflow-auto rounded-lg border border-line">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface-2 text-left text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Period</th>
                  {table.columns.map((c) => (
                    <th key={c.label} className="px-3 py-2 text-right font-medium">
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {table.rowLabels.map((label, i) => (
                  <tr key={`${label}-${i}`} className="border-t border-line">
                    <td className="px-3 py-1.5 text-text-3">{label}</td>
                    {table.columns.map((c) => (
                      <td key={c.label} className="px-3 py-1.5 text-right text-text-2">
                        {c.values[i]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          children
        )}
      </div>
    </Card>
  );
};
