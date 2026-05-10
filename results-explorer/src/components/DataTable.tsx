import type { ComponentChildren } from "preact";
import { TableScrollHint } from "@/components/TableScrollHint";

interface DataTableProps {
  ariaLabel?: string;
  caption?: ComponentChildren;
  /** When true, wraps the table in a horizontally scrollable region with sticky first column support. */
  scrollable?: boolean;
  class?: string;
  children: ComponentChildren;
}

export function DataTable({ ariaLabel, caption, scrollable = false, class: extraClass = "", children }: DataTableProps) {
  const inner = (
    <table aria-label={ariaLabel} class={`w-full text-sm ${extraClass}`}>
      {caption && <caption class="text-left text-xs uppercase tracking-wide text-[var(--bb-data-fg-subtle)] py-2">{caption}</caption>}
      {children}
    </table>
  );
  if (!scrollable) return inner;
  return (
    <div>
      <TableScrollHint
        label="Scroll table for more columns →"
        wrapperClassName="flex justify-end"
        className="mb-2"
      />
      <div class="overflow-x-auto">{inner}</div>
    </div>
  );
}

interface TableHeadProps {
  /** Apply sticky top positioning. The Panel must define overflow boundaries. */
  sticky?: boolean;
  class?: string;
  children: ComponentChildren;
}

export function TableHead({ sticky = false, class: extraClass = "", children }: TableHeadProps) {
  const stickyClass = sticky
    ? `sticky top-0 z-[1]`
    : "";
  return (
    <thead
      class={`bg-[var(--bb-surface-data-muted)] text-[var(--bb-data-fg-subtle)] ${stickyClass} ${extraClass}`}
    >
      {children}
    </thead>
  );
}

interface TableProps {
  class?: string;
  children: ComponentChildren;
}

export function TableBody({ class: extraClass = "", children }: TableProps) {
  return <tbody class={`divide-y divide-[var(--bb-data-border)] ${extraClass}`}>{children}</tbody>;
}

export default DataTable;
