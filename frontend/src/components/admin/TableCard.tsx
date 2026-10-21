import type { ReactNode } from 'react';
import { Card } from '../ui';

/** A small titled table: the first column names the row, the others are right-aligned numbers. */
export const TableCard = ({ title, subtitle, head, rows, empty, aside }: { title: string; subtitle?: ReactNode; head: string[]; rows: ReactNode[][]; empty: string; aside?: ReactNode }) => (
  <Card padding="sm" className="min-w-0">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-text-2">{title}</h3>
        {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
      </div>
      {aside && <div className="shrink-0 text-xs text-muted">{aside}</div>}
    </div>
    {rows.length === 0 ? (
      <p className="mt-4 text-sm text-muted">{empty}</p>
    ) : (
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted">
            <tr>
              {head.map((h, i) => (
                <th key={h} className={`pb-2 font-medium ${i === 0 ? '' : 'whitespace-nowrap pl-3 text-right'}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((cells, r) => (
              <tr key={r} className="border-t border-line">
                {cells.map((cell, i) => (
                  <td key={i} className={`py-2 ${i === 0 ? 'pr-3 text-text-2' : 'pl-3 text-right text-text-3 whitespace-nowrap'}`}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </Card>
);
