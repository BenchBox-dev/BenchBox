import type { DetailResult } from "@/types";
import { StatusBadge } from "@/components/StatusBadge";
import { buildComparabilityFields, type ComparabilityField } from "@/components/ComparabilityReceipt";
import { formatCpuIdentityProvenance } from "@/lib/hardwareProvenance";

/**
 * The engine-and-hardware strip for a head-to-head comparison.
 *
 * Answers one question at a glance: of the things that could explain a
 * difference in these numbers, which ones ACTUALLY differ between these two
 * runs? A reader looking at a 1.4x speedup needs to know whether the engines
 * differ, or the hardware does, or only the engine version.
 *
 * It does NOT replace or duplicate the ComparabilityReceipt, which stays on
 * the page and remains the full record. The strip summarizes the
 * axes most likely to confound an engine comparison; the receipt covers
 * benchmark, scale, phase, query scope, dates, tuning, validation and cost as
 * well. Both read the SAME `buildComparabilityFields` output, so the strip can
 * never disagree with the receipt about whether an axis differs -- which is
 * exactly what a second, independently-derived summary would eventually do.
 */
export interface IdentityDiffStripProps {
  results: DetailResult[];
  baselineIndex?: number;
  runLabels?: readonly string[];
}

/** The axes this strip reports, in reading order, by their receipt labels. */
export const STRIP_AXES = [
  "Platform version",
  "Driver version",
  "Architecture",
  "CPU family",
  "CPU model",
  "CPU evidence",
  "Memory",
] as const;

export const AXIS_DISPLAY_LABEL: Record<(typeof STRIP_AXES)[number], string> = {
  "Platform version": "Engine version",
  "Driver version": "Driver",
  Architecture: "Architecture",
  "CPU family": "CPU family",
  "CPU model": "CPU model",
  "CPU evidence": "CPU evidence",
  Memory: "Memory",
};

export function axisValueForRun(axis: (typeof STRIP_AXES)[number], result: DetailResult): string {
  switch (axis) {
    case "Platform version":
      return result.platform_version && result.platform_version !== "" ? result.platform_version : "Not recorded";
    case "Driver version":
      return result.driver_version && result.driver_version !== "" ? result.driver_version : "Not recorded";
    case "Architecture":
      return result.environment?.arch && result.environment.arch !== "" ? result.environment.arch : "Not recorded";
    case "CPU family":
      return result.environment?.cpu_family && result.environment.cpu_family !== "" ? result.environment.cpu_family : "Not recorded";
    case "CPU model":
      return result.environment?.cpu_model && result.environment.cpu_model !== "" ? result.environment.cpu_model : "Not recorded";
    case "CPU evidence":
      return formatCpuIdentityProvenance(result.environment?.cpu_identity_provenance);
    case "Memory":
      return result.environment?.memory_gb !== undefined ? `${result.environment.memory_gb} GB` : "Not recorded";
  }
}

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

export function IdentityDiffStrip({ results, baselineIndex = 0, runLabels }: IdentityDiffStripProps) {
  if (results.length < 2) return null;
  const fields = identityStripFields(results);
  if (fields.length === 0) return null;
  const diffCount = fields.filter((f) => f.status === "diff").length;

  if (results.length > 2) {
    const baseIndex = results[baselineIndex] ? baselineIndex : 0;
    const baselineRun = results[baseIndex];

    return (
      <section class="panel mb-4 px-3 py-2 shadow-sm" aria-label="Engine and hardware identity">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-medium text-[var(--bb-data-fg-primary)]">Engine and hardware</h2>
          <p class="text-xs text-[var(--bb-data-fg-muted)]">
            {diffCount === 0
              ? `No differences were recorded for these ${fields.length} fields. Other recorded or unrecorded factors may differ.`
              : `${diffCount} of ${fields.length} ${diffCount === 1 ? "axis varies" : "axes vary"} across the whole selection.`}
          </p>
        </div>
        <div class="mt-2 overflow-x-auto">
          <table role="table" class="min-w-full w-max divide-y divide-[var(--bb-data-border)] text-sm">
            <thead class="bg-[var(--bb-surface-data-muted)]">
              <tr>
                <th class="table-th">Axis</th>
                {results.map((r, i) => (
                  <th key={r.result_id} class="table-th">
                    {runLabels?.[i] ?? r.platform}
                    {i === baseIndex ? " (baseline)" : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
              {fields.map((field) => {
                const axis = field.label as (typeof STRIP_AXES)[number];
                const baseVal = baselineRun ? axisValueForRun(axis, baselineRun) : "Not recorded";
                return (
                  <tr key={field.label}>
                    <td class="table-td font-medium text-[var(--bb-data-fg-primary)]">
                      {AXIS_DISPLAY_LABEL[axis] ?? field.label}
                    </td>
                    {results.map((r, i) => {
                      const val = axisValueForRun(axis, r);
                      const isBase = i === baseIndex;
                      const candidateMissing = val === "Not recorded";
                      const baselineMissing = baseVal === "Not recorded";
                      const isDiff = !isBase && !candidateMissing && !baselineMissing && val !== baseVal;
                      const status = isBase
                        ? "baseline"
                        : candidateMissing
                          ? "missing"
                          : baselineMissing
                            ? "indeterminate"
                            : isDiff
                              ? "diff"
                              : "match";
                      return (
                        <td key={r.result_id} class="table-td text-xs" data-testid={`matrix-cell-${axis}-${i}`}>
                          <div class="flex items-center justify-between gap-2">
                            <span class="break-words font-mono text-[var(--bb-data-fg-primary)]">{val}</span>
                            <StatusBadge
                              role="comparison"
                              tone={status === "diff" ? "warning" : status === "match" ? "success" : "neutral"}
                            >
                              {status === "baseline"
                                ? "Baseline"
                                : status === "indeterminate"
                                  ? "No baseline"
                                  : statusWord(status)}
                            </StatusBadge>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  return (
    <section class="panel mb-4 px-3 py-2 shadow-sm" aria-label="Engine and hardware identity">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-sm font-medium text-[var(--bb-data-fg-primary)]">Engine and hardware</h2>
        <p class="text-xs text-[var(--bb-data-fg-muted)]">
          {diffCount === 0
            ? `No differences were recorded for these ${fields.length} fields. Other recorded or unrecorded factors may differ.`
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
