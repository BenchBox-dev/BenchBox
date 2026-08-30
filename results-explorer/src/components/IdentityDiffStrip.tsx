import type { DetailResult } from "@/types";
import { StatusBadge } from "@/components/StatusBadge";
import { buildComparabilityFields, type ComparabilityField } from "@/components/ComparabilityReceipt";

/**
 * The six-axis engine-and-hardware strip for a head-to-head comparison.
 *
 * Answers one question at a glance: of the things that could explain a
 * difference in these numbers, which ones ACTUALLY differ between these two
 * runs? A reader looking at a 1.4x speedup needs to know whether the engines
 * differ, or the hardware does, or only the engine version.
 *
 * It does NOT replace or duplicate the ComparabilityReceipt, which stays on
 * the page and remains the full record. The strip is a six-axis summary of the
 * axes most likely to confound an engine comparison; the receipt covers
 * benchmark, scale, phase, query scope, dates, tuning, validation and cost as
 * well. Both read the SAME `buildComparabilityFields` output, so the strip can
 * never disagree with the receipt about whether an axis differs -- which is
 * exactly what a second, independently-derived summary would eventually do.
 */
export interface IdentityDiffStripProps {
  results: DetailResult[];
}

/** The axes this strip reports, in reading order, by their receipt labels. */
const STRIP_AXES = [
  "Platform version",
  "Driver version",
  "Architecture",
  "CPU family",
  "CPU model",
  "Memory",
] as const;

const AXIS_DISPLAY_LABEL: Record<(typeof STRIP_AXES)[number], string> = {
  "Platform version": "Engine version",
  "Driver version": "Driver",
  Architecture: "Architecture",
  "CPU family": "CPU family",
  "CPU model": "CPU model",
  Memory: "Memory",
};

export function identityStripFields(results: DetailResult[]): ComparabilityField[] {
  if (results.length === 0) return [];
  const byLabel = new Map(buildComparabilityFields(results).map((field) => [field.label, field]));
  return STRIP_AXES.map((label) => byLabel.get(label)).filter(
    (field): field is ComparabilityField => field !== undefined,
  );
}

/** How many of the strip's axes actually differ between the runs. */
export function identityStripDiffCount(results: DetailResult[]): number {
  return identityStripFields(results).filter((field) => field.status === "diff").length;
}

function toneFor(status: ComparabilityField["status"]): "success" | "warning" | "neutral" {
  if (status === "diff") return "warning";
  if (status === "missing") return "neutral";
  return "success";
}

function statusWord(status: ComparabilityField["status"]): string {
  if (status === "diff") return "Differs";
  if (status === "missing") return "Not recorded";
  return "Same";
}

export function IdentityDiffStrip({ results }: IdentityDiffStripProps) {
  if (results.length < 2) return null;
  const fields = identityStripFields(results);
  if (fields.length === 0) return null;
  const diffCount = fields.filter((f) => f.status === "diff").length;

  return (
    <section class="panel mb-4 px-3 py-2 shadow-sm" aria-label="Engine and hardware identity">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-sm font-medium text-[var(--bb-data-fg-primary)]">Engine and hardware</h2>
        <p class="text-xs text-[var(--bb-data-fg-muted)]">
          {diffCount === 0
            ? "These runs match on every axis below, so the difference is not explained by them."
            : `${diffCount} of ${fields.length} ${diffCount === 1 ? "axis differs" : "axes differ"} between these runs.`}
        </p>
      </div>
      <ul class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {fields.map((field) => (
          <li key={field.label} class="flex items-start justify-between gap-2 rounded-md border border-[var(--bb-data-border-strong)] px-2 py-1.5">
            <div class="min-w-0">
              <p class="text-xs font-medium text-[var(--bb-data-fg-primary)]">
                {AXIS_DISPLAY_LABEL[field.label as (typeof STRIP_AXES)[number]] ?? field.label}
              </p>
              <p class="text-xs text-[var(--bb-data-fg-muted)] break-words">{field.summary}</p>
            </div>
            <StatusBadge role="comparison" tone={toneFor(field.status)}>
              {statusWord(field.status)}
            </StatusBadge>
          </li>
        ))}
      </ul>
    </section>
  );
}
