import { useEffect, useMemo, useRef, useState } from "preact/hooks";
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

const FOCUSABLE_DRAWER_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

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
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onOpenChange(false);
        return;
      }
      if (event.key !== "Tab" || !dialog) return;

      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_DRAWER_SELECTOR),
      ).filter((element) => element.tabIndex >= 0 && !element.getAttribute("aria-hidden"));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0]!;
      const last = focusable.at(-1)!;
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === dialog) {
        event.preventDefault();
        first.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [open, onOpenChange]);

  return (
    <div class="space-y-3" aria-label="Mobile result facets">
      <button
        type="button"
        class="flex w-full items-center justify-between gap-3 rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-2 text-left text-sm shadow-sm"
        aria-expanded={open}
        data-result-count={resultCount}
        onClick={() => onOpenChange(!open)}
      >
        <span class="min-w-0">
          <span class="font-medium text-[var(--bb-data-fg-primary)]">Filters</span>
          {activeChips.length > 0 && <ActiveChipPreview activeChips={activeChips} />}
        </span>
        <span class="shrink-0 text-xs text-[var(--bb-data-fg-muted)]">{resultCount.toLocaleString()} results</span>
      </button>
      {activeChips.length > 0 && (
        <ActiveChipStrip activeChips={activeChips} onReset={onReset} compact />
      )}
      {open && (
        <>
          <button
            type="button"
            aria-label="Close filters"
            class="fixed inset-0 z-40 bg-[var(--bb-bg-primary)]/40 sm:hidden"
            onClick={() => onOpenChange(false)}
          />
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Filter results"
            tabIndex={-1}
            class="fixed inset-0 z-50 overflow-y-auto bg-[var(--bb-surface-data)] p-3 shadow-2xl outline-none sm:static sm:rounded-lg sm:border sm:border-[var(--bb-data-border)] sm:shadow-lg"
          >
            <div class="mb-3 flex items-center justify-between gap-3 border-b border-[var(--bb-data-border)] pb-3 sm:hidden">
              <h2 class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">Filters</h2>
              <button
                type="button"
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-1.5 text-sm font-medium text-[var(--bb-data-fg-primary)]"
                onClick={() => onOpenChange(false)}
              >
                Done
              </button>
            </div>
            <FacetRail
              groups={groups}
              resultCount={resultCount}
              activeChips={activeChips}
              onToggle={onToggle}
              onReset={onReset}
            />
            <div class="mt-4 flex gap-2 border-t border-gray-200 pt-3 lg:hidden">
              <button
                type="button"
                class="flex-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700"
                onClick={onReset}
              >
                Reset filters
              </button>
              <button
                type="button"
                class="flex-1 rounded-md border border-brand-600 bg-brand-600 px-3 py-2 text-sm font-medium text-white"
                onClick={() => onOpenChange(false)}
              >
                Apply filters
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ActiveChipPreview({ activeChips }: { activeChips: ActiveFacetChip[] }) {
  return (
    <span class="mt-1 flex flex-wrap gap-1">
      {activeChips.map((chip) => (
        <span
          key={chip.key}
          class="max-w-32 truncate rounded-full bg-[var(--bb-tone-info-bg)] px-2 py-0.5 text-[11px] font-medium text-[var(--bb-tone-info-fg)]"
        >
          {chip.label}
        </span>
      ))}
    </span>
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
    <section class="rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-4 shadow-sm">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">Filters</h2>
          <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">{resultCount.toLocaleString()} matching results</p>
        </div>
        <button type="button" class="text-xs font-medium text-[var(--bb-accent-hover)] hover:underline" onClick={onReset}>
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
          class="rounded-full bg-[var(--bb-tone-info-bg)] px-3 py-1 text-xs font-medium text-[var(--bb-tone-info-fg)] hover:bg-[var(--bb-tone-neutral-bg)]"
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
    <section class="rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-4 shadow-sm">
      <div class="mb-3 flex items-center justify-between gap-2">
        <h3 class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">{group.label}</h3>
        {group.selected.length > 0 && (
          <span class="rounded-full bg-[var(--bb-surface-app)] px-2 py-0.5 text-xs text-[var(--bb-data-fg-muted)]">
            {group.selected.length}
          </span>
        )}
      </div>
      {group.searchable && (
        <label class="mb-3 block">
          <span class="sr-only">Search {group.label}</span>
          <input
            type="search"
            class="w-full rounded-md border border-[var(--bb-data-border-strong)] px-3 py-1.5 text-sm"
            placeholder={`Search ${group.label.toLowerCase()}`}
            value={search}
            onInput={(event) => setSearch((event.currentTarget as HTMLInputElement).value)}
          />
        </label>
      )}
      {options.length === 0 ? (
        <p class="text-sm text-[var(--bb-data-fg-subtle)]">{group.emptyLabel ?? "No facet values"}</p>
      ) : (
        <div class="space-y-2">
          {options.map((option) => {
            const checked = group.selected.includes(option.value);
            return (
              <label key={option.value} class="flex items-center justify-between gap-2 text-sm text-[var(--bb-data-fg-muted)]">
                <span class="inline-flex min-w-0 items-center gap-2">
                  <input
                    type="checkbox"
                    aria-label={formatFacetAccessibleName(group.label, option.displayLabel, option.count)}
                    checked={checked}
                    disabled={option.disabled}
                    onChange={() => onToggle(group.key, option.value)}
                  />
                  <span class="truncate">{option.displayLabel}</span>
                </span>
                {option.count !== undefined && (
                  <span class="shrink-0 text-xs text-[var(--bb-data-fg-subtle)]">{option.count.toLocaleString()}</span>
                )}
              </label>
            );
          })}
        </div>
      )}
    </section>
  );
}

function formatFacetAccessibleName(groupLabel: string, optionLabel: string, count?: number): string {
  const countSuffix = count === undefined ? "" : ` (${count.toLocaleString()})`;
  return `${groupLabel}: ${optionLabel}${countSuffix}`;
}

function facetKeyFromChipKey(key: string): string {
  return key.split(":", 1)[0] ?? key;
}
