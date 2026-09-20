import type { ReactNode } from "react";

export interface DataTableColumn<T> {
  header: ReactNode;
  key: string;
  cell: (row: T, index: number) => ReactNode;
  className?: string;
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  keyFor: (row: T, index: number) => string;
  emptyMessage?: string;
}

/** Dense, professional data table primitive shared across explorer pages. */
export function DataTable<T>({ columns, rows, keyFor, emptyMessage = "No data." }: DataTableProps<T>) {
  if (rows.length === 0) {
    return <div className="rounded-lg border border-surface-border bg-surface-raised p-6 text-center text-sm text-slate-400">{emptyMessage}</div>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-surface-border">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-surface-border bg-surface-raised text-left text-xs uppercase tracking-wide text-slate-400">
            {columns.map((col) => (
              <th key={col.key} className={`px-3 py-2 font-medium ${col.className ?? ""}`}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={keyFor(row, i)} className="border-b border-surface-border/60 last:border-0 hover:bg-surface-raised/60">
              {columns.map((col) => (
                <td key={col.key} className={`px-3 py-2 align-top text-slate-200 ${col.className ?? ""}`}>
                  {col.cell(row, i)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
