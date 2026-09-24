/**
 * The one cohort filter panel shared by BenchmarkIndex and PlatformIndex.
 *
 * Both pages narrow the same kind of cohort (scale, phase, tuning, platform
 * version, trust tier, validation, architecture, CPU family, memory, run
 * date) with only the pivot column differing - the benchmark page fixes the
 * benchmark and lets the reader pick a platform, the platform page fixes the
 * platform and lets the reader pick a benchmark. Each page supplies its own
 * ordered field list; this component only owns the layout, the disabled
 * state, and the "Clear filters" affordance.
 */
export interface CohortFilterOption {
  value: string;
  label: string;
}

export interface CohortFilterFieldSpec {
  /** Element id; also used as the React key. */
  id: string;
  /** `data-testid` on the `<select>`, when a test or e2e spec depends on it. */
  testId?: string;
  label: string;
  value: string;
  options: CohortFilterOption[];
  onChange: (value: string) => void;
  /** Non-null disables the select and becomes its `title`. */
  disabledReason?: string | null;
  /**
   * An extra disabled option shown only while `value` equals its own value -
   * the "N tiers selected" / "N versions selected" placeholder for a facet
   * whose URL state can hold more values than this single-select can offer.
   */
  multiValueOption?: CohortFilterOption;
}

interface CohortFilterPanelProps {
  fields: CohortFilterFieldSpec[];
  showClear: boolean;
  onClear: () => void;
  clearTestId?: string;
  /** `data-testid` on the outer `<section>`, when an e2e spec depends on it. */
  testId?: string;
}

const SELECT_CLASS =
  "rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm shadow-sm disabled:cursor-not-allowed disabled:opacity-50";

export function CohortFilterPanel({ fields, showClear, onClear, clearTestId, testId }: CohortFilterPanelProps) {
  return (
    <section
      class="mb-4 min-w-0 grid grid-cols-1 gap-x-4 gap-y-3 rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-4 py-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
      data-testid={testId}
      aria-label="Cohort filters"
    >
      {fields.map((field) => (
        <CohortFilterField key={field.id} {...field} />
      ))}
      {showClear && (
        <div class="flex items-end">
          <button type="button" class="btn btn-subtle text-sm" data-testid={clearTestId} onClick={onClear}>
            Clear filters
          </button>
        </div>
      )}
    </section>
  );
}

function CohortFilterField({
  id,
  testId,
  label,
  value,
  options,
  onChange,
  disabledReason,
  multiValueOption,
}: CohortFilterFieldSpec) {
  const disabled = Boolean(disabledReason);
  return (
    <div class="min-w-0 flex flex-col gap-1">
      <label class="text-xs font-medium text-[var(--bb-data-fg-muted)]" for={id}>
        {label}
      </label>
      <select
        id={id}
        data-testid={testId}
        class={`${SELECT_CLASS} w-full min-w-0 max-w-full`}
        value={value}
        disabled={disabled}
        title={disabledReason ?? undefined}
        onChange={(event) => onChange((event.target as HTMLSelectElement).value)}
      >
        {multiValueOption && value === multiValueOption.value && (
          <option value={multiValueOption.value} disabled>
            {multiValueOption.label}
          </option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
