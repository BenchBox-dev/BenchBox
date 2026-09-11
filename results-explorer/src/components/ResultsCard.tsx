import type { ComponentChildren } from "preact";
import { COHORT_GROUP_BY_LABELS, type CohortGroupBy } from "@/lib/queryFilters";

/**
 * Toolbar row shared by the Results card on the Benchmark and Platform
 * pages: a left slot (empty on the Benchmark page, the measurement basis
 * control on the Platform page) and a right slot (the Group by control on
 * both).
 */
export function ResultsCardToolbar({ left, right }: { left?: ComponentChildren; right: ComponentChildren }) {
  return (
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]">
      <div class="flex flex-wrap items-center gap-3">{left}</div>
      <div class="flex items-center gap-2">{right}</div>
    </div>
  );
}

export function GroupBySelect({
  id,
  testId,
  value,
  onChange,
}: {
  id: string;
  testId?: string;
  value: CohortGroupBy;
  onChange: (value: CohortGroupBy) => void;
}) {
  return (
    <div class="flex items-center gap-2">
      <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for={id}>
        Group by:
      </label>
      <select
        id={id}
        data-testid={testId}
        class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm shadow-sm"
        value={value}
        onChange={(event) => onChange((event.target as HTMLSelectElement).value as CohortGroupBy)}
      >
        <option value="none">{COHORT_GROUP_BY_LABELS.none}</option>
        <option value="engine_version">{COHORT_GROUP_BY_LABELS.engine_version}</option>
      </select>
    </div>
  );
}

/** The basis-statement strip: identical wrapper classes on both pages, different wording. */
export function ResultsBasisStatement({ children }: { children: ComponentChildren }) {
  return (
    <p class="mb-3 text-xs text-[var(--bb-data-fg-muted)]" data-testid="basis-statement">
      {children}
    </p>
  );
}
