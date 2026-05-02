import { useMemo, useState } from "preact/hooks";
import { formatFacetDisplayValue } from "@/lib/facetDisplay";

export interface FacetOption {
  value: string;
  label: string;
  count?: number;
  disabled?: boolean;
}

export interface FacetGroup {
  key: string;
  label: string;
  options: FacetOption[];
  selected: string[];
  searchable?: boolean;
  emptyLabel?: string;
}

export interface ActiveFacetChip {
  key: string;
  label: string;
  facetKey?: string;
  value?: string;
  onClear?: () => void;
}

export interface FacetRailProps {
  groups: FacetGroup[];
  resultCount: number;
  activeChips?: ActiveFacetChip[];
  onToggle: (groupKey: string, value: string) => void;
  onReset: () => void;
}

export interface FacetDrawerProps extends FacetRailProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function FacetRail({ groups, resultCount, activeChips = [], onToggle, onReset }: FacetRailProps) {
  return (
    <aside class="space-y-3" aria-label="Result facets">
      <FacetSummary resultCount={resultCount} activeChips={activeChips} onReset={onReset} />
      {groups.map((group) => (
        <FacetGroupSection key={group.key} group={group} onToggle={onToggle} />
      ))}
    </aside>
  );
}

export function FacetDrawer({
  groups,
  resultCount,
  activeChips = [],
  onToggle,
  onReset,
  open,
  onOpenChange,
}: FacetDrawerProps) {
  return (
    <div class="space-y-3" aria-label="Mobile result facets">
      <button
        type="button"
        class="flex w-full items-center justify-between rounded-md border border-gray-300 bg-white px-3 py-2 text-left text-sm shadow-sm"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
      >
        <span class="font-medium text-gray-900">Filters</span>
        <span class="text-xs text-gray-500">{resultCount.toLocaleString()} results</span>
      </button>
      {activeChips.length > 0 && (
        <ActiveChipStrip activeChips={activeChips} onReset={onReset} compact />
      )}
      {open && (
        <div
          role="dialog"
          aria-label="Filter results"
          class="rounded-lg border border-gray-200 bg-white p-3 shadow-lg"
        >
          <FacetRail
            groups={groups}
            resultCount={resultCount}
            activeChips={activeChips}
            onToggle={onToggle}
            onReset={onReset}
          />
        </div>
      )}
    </div>
  );
}

function FacetSummary({
  resultCount,
  activeChips,
  onReset,
}: {
  resultCount: number;
  activeChips: ActiveFacetChip[];
  onReset: () => void;
}) {
  return (
    <section class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold text-gray-900">Filters</h2>
          <p class="mt-1 text-xs text-gray-500">{resultCount.toLocaleString()} matching results</p>
        </div>
        <button type="button" class="text-xs font-medium text-brand-700 hover:text-brand-900" onClick={onReset}>
          Reset
        </button>
      </div>
      {activeChips.length > 0 && <ActiveChipStrip activeChips={activeChips} onReset={onReset} />}
    </section>
  );
}

function ActiveChipStrip({
  activeChips,
  onReset,
  compact = false,
}: {
  activeChips: ActiveFacetChip[];
  onReset: () => void;
  compact?: boolean;
}) {
  return (
    <div class={compact ? "flex flex-wrap gap-2" : "mt-3 flex flex-wrap gap-2"}>
      {activeChips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          class="rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 hover:bg-brand-100"
          onClick={chip.onClear ?? onReset}
        >
          {chip.value === undefined
            ? chip.label
            : formatFacetDisplayValue(chip.facetKey ?? facetKeyFromChipKey(chip.key), chip.value, chip.label)}
        </button>
      ))}
    </div>
  );
}

function FacetGroupSection({
  group,
  onToggle,
}: {
  group: FacetGroup;
  onToggle: (groupKey: string, value: string) => void;
}) {
  const [search, setSearch] = useState("");
  const options = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const labelled = group.options.map((option) => ({
      ...option,
      displayLabel: formatFacetDisplayValue(group.key, option.value, option.label),
    }));
    if (needle === "") return labelled;
    return labelled.filter(
      (option) =>
        option.displayLabel.toLowerCase().includes(needle) || option.value.toLowerCase().includes(needle),
    );
  }, [group.options, search]);

  return (
    <section class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div class="mb-3 flex items-center justify-between gap-2">
        <h3 class="text-sm font-semibold text-gray-900">{group.label}</h3>
        {group.selected.length > 0 && (
          <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
            {group.selected.length}
          </span>
        )}
      </div>
      {group.searchable && (
        <label class="mb-3 block">
          <span class="sr-only">Search {group.label}</span>
          <input
            type="search"
            class="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
            placeholder={`Search ${group.label.toLowerCase()}`}
            value={search}
            onInput={(event) => setSearch((event.currentTarget as HTMLInputElement).value)}
          />
        </label>
      )}
      {options.length === 0 ? (
        <p class="text-sm text-gray-400">{group.emptyLabel ?? "No facet values"}</p>
      ) : (
        <div class="space-y-2">
          {options.map((option) => {
            const checked = group.selected.includes(option.value);
            return (
              <label key={option.value} class="flex items-center justify-between gap-2 text-sm text-gray-600">
                <span class="inline-flex min-w-0 items-center gap-2">
                  <input
                    type="checkbox"
                    aria-label={option.displayLabel}
                    checked={checked}
                    disabled={option.disabled}
                    onChange={() => onToggle(group.key, option.value)}
                  />
                  <span class="truncate">{option.displayLabel}</span>
                </span>
                {option.count !== undefined && (
                  <span class="shrink-0 text-xs text-gray-400">{option.count.toLocaleString()}</span>
                )}
              </label>
            );
          })}
        </div>
      )}
    </section>
  );
}

function facetKeyFromChipKey(key: string): string {
  return key.split(":", 1)[0] ?? key;
}
