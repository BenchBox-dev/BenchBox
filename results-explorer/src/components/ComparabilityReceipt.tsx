import type { DetailResult, Environment } from "@/types";
import { humanizeBenchmark, shortHash } from "@/utils";
import { costModelSummary, costScopeSummary, normalizedCostLabel } from "@/lib/costDisplay";
import { formatCount, formatWarningCount } from "@/lib/copyFormatters";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";

interface ComparabilityReceiptProps {
  results: DetailResult[];
}

type ComparabilityStatus = "match" | "diff" | "missing";

export const COMPARABILITY_RECEIPT_ID = "comparability-receipt";
export const COMPARABILITY_WARNING_TARGET_ID = "comparability-receipt-warnings";

export interface ComparabilityField {
  label: string;
  status: ComparabilityStatus;
  summary: string;
  detail?: string;
}

export function ComparabilityReceipt({ results }: ComparabilityReceiptProps) {
  if (results.length === 0) return null;

  const fields = buildComparabilityFields(results);
  const warningFields = comparabilityWarningFields(fields);
  const warningCount = warningFields.length;

  return (
    <section id={COMPARABILITY_RECEIPT_ID} aria-label="Comparability receipt" class="panel-elevated mb-8 p-4">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">Comparability Receipt</h2>
          <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">
            Workload, version, validation, and environment checks for the selected result set.
          </p>
        </div>
        <StatusBadge role="comparison" tone={warningCount > 0 ? "warning" : "success"}>
          {warningCount > 0 ? formatWarningCount(warningCount) : "No differences"}
        </StatusBadge>
      </div>

      {warningCount > 0 && (
        <section
          id={COMPARABILITY_WARNING_TARGET_ID}
          tabIndex={-1}
          aria-label="Warning details"
          class="mb-4 rounded-md border border-[var(--bb-tone-warning-border)] bg-[var(--bb-tone-warning-bg)] px-3 py-2 text-xs text-[var(--bb-tone-warning-fg)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--bb-accent)]"
          data-testid="comparability-warning-target"
        >
          <h3 class="font-semibold">{formatWarningCount(warningCount)}</h3>
          <ul class="mt-1 list-disc space-y-1 pl-4">
            {warningFields.map((field) => (
              <li key={field.label}>
                <span class="font-medium">{field.label}:</span> {field.summary}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {fields.map((field) => (
          <ComparabilityFieldRow key={field.label} field={field} />
        ))}
      </div>
    </section>
  );
}

export function buildComparabilityFields(results: DetailResult[]): ComparabilityField[] {
  if (results.length === 0) return [];

  const fields: ComparabilityField[] = [
    compareValues("Benchmark", results, (result) => humanizeBenchmark(result.benchmark)),
    compareValues("Scale factor", results, (result) => `SF ${result.scale_factor}`),
    compareValues("Phase", results, (result) => valueOrMissing(result.test_type)),
    compareValues("Query scope", results, (result) => formatCount(queryCount(result), "query", "queries")),
    buildDateWindowField(results),
    compareValues("Platform version", results, (result) => valueOrMissing(result.platform_version)),
    compareValues("Driver version", results, (result) => valueOrMissing(result.driver_version)),
    compareValues("Execution mode", results, (result) => valueOrMissing(result.execution_mode)),
    buildTuningField(results),
    compareValues("Validation", results, (result) => valueOrMissing(result.validation_status)),
    buildEnvironmentField(results),
    compareValues("Normalized cost", results, normalizedCostLabel),
    compareValues("Cost model", results, costModelSummary),
    compareValues("Cost scope", results, costScopeSummary),
  ];

  const physicalMechanismsField = buildPhysicalMechanismsField(results);
  if (physicalMechanismsField) fields.push(physicalMechanismsField);

  const tuningPolicyGenerationField = buildTuningPolicyGenerationField(results);
  if (tuningPolicyGenerationField) fields.push(tuningPolicyGenerationField);

  return fields;
}

/**
 * The generation attributed to tuned runs that predate the ADR-3
 * tuning-policy generation marker (absent `tuning_policy_generation`). Unlike
 * the physical-mechanisms warning -- which treats `undefined` as "unknown, do
 * not compare" -- an absent generation is a *concrete* value here: two legacy
 * runs are same-generation (no warning), but a legacy run compared against a
 * marked run IS a cross-seam comparison (warning). See ADR-3.
 */
const PRE_SEAM_GENERATION = "pre-seam";

/**
 * ADR-3 seam: warn (never fail the match) when two or more `tuned` runs were
 * produced under different tuning-policy generations. Tuning policy evolves
 * across a generation seam (ADR-3's baseline redefinition + single-renderer
 * consolidation), so tuned results from different generations are not directly
 * comparable -- exactly the concern the cross-mechanism warning above handles
 * for physical mechanisms. Mirrors that warning's shape, with one deliberate
 * difference: an absent marker is the concrete "pre-seam" generation, not
 * "unknown" -- so two legacy runs stay same-generation (no warning), while a
 * legacy-vs-marked pair warns. Returns null when there's nothing to compare
 * (fewer than two `tuned` runs). This is a WARNING only: facet matching is
 * unchanged and the generation is never a match/dedup/grouping key.
 */
function buildTuningPolicyGenerationField(results: DetailResult[]): ComparabilityField | null {
  const tunedResults = results.filter((result) => result.tuning_mode === "tuned");
  if (tunedResults.length < 2) return null;

  const generationOf = (result: DetailResult) => result.tuning_policy_generation ?? PRE_SEAM_GENERATION;
  const uniqueGenerations = [...new Set(tunedResults.map(generationOf))];

  if (uniqueGenerations.length === 1) {
    return {
      label: "Tuning policy generation",
      status: "match",
      summary: uniqueGenerations[0]!,
    };
  }

  return {
    label: "Tuning policy generation",
    status: "diff",
    summary: "Tuned runs span different tuning-policy generations",
    detail: formatPerPlatform(
      tunedResults.map((result) => ({
        platform: result.platform,
        value: generationOf(result),
      })),
    ),
  };
}

/**
 * ADR-2 §3: warn (never fail the match) when two or more results labeled
 * `tuned` rendered different sets of physical tuning mechanisms (indexes,
 * clustering keys, distribution styles, etc.) -- e.g. one platform renders
 * six mechanisms for a template and another renders zero, invisibly to the
 * coarse `tuning_mode` facet. Returns null when there's nothing to compare:
 * fewer than two `tuned` results, or any of them predates ingest recording
 * `physical_mechanisms` (undefined, not merely empty -- an empty array is a
 * meaningful "rendered nothing" value, not "unknown").
 */
function buildPhysicalMechanismsField(results: DetailResult[]): ComparabilityField | null {
  const tunedResults = results.filter((result) => result.tuning_mode === "tuned");
  if (tunedResults.length < 2) return null;
  if (tunedResults.some((result) => result.physical_mechanisms === undefined)) return null;

  const sets = tunedResults.map((result) => new Set(result.physical_mechanisms ?? []));
  const allMatch = sets.every((set) => setsEqual(set, sets[0]!));

  if (allMatch) {
    const count = sets[0]!.size;
    return {
      label: "Physical tuning mechanisms",
      status: "match",
      summary: count > 0 ? formatCount(count, "mechanism", "mechanisms") : "None rendered",
    };
  }

  return {
    label: "Physical tuning mechanisms",
    status: "diff",
    summary: "Tuned runs rendered different physical mechanisms",
    detail: formatPerPlatform(
      tunedResults.map((result) => ({
        platform: result.platform,
        value: (result.physical_mechanisms ?? []).join(", ") || "none",
      })),
    ),
  };
}

function setsEqual(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a.size !== b.size) return false;
  for (const item of a) {
    if (!b.has(item)) return false;
  }
  return true;
}

export function comparabilityWarningFields(fields: readonly ComparabilityField[]): ComparabilityField[] {
  return fields.filter((field) => field.status === "diff");
}

function ComparabilityFieldRow({ field }: { field: ComparabilityField }) {
  return (
    <div class="rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-2">
      <div class="mb-1 flex items-center justify-between gap-2">
        <h3 class="text-xs font-semibold uppercase text-[var(--bb-data-fg-subtle)]">{field.label}</h3>
        <StatusBadge role="comparison" tone={statusTone(field.status)}>{statusLabel(field.status)}</StatusBadge>
      </div>
      <p class="break-words text-xs font-medium text-[var(--bb-data-fg-primary)]">{field.summary}</p>
      {field.detail && <p class="mt-1 break-words text-xs text-[var(--bb-data-fg-muted)]">{field.detail}</p>}
    </div>
  );
}

function compareValues(
  label: string,
  results: DetailResult[],
  readValue: (result: DetailResult) => string,
): ComparabilityField {
  const entries = results.map((result) => ({
    platform: result.platform,
    value: readValue(result),
  }));
  const values = entries.map((entry) => entry.value);
  const uniqueValues = [...new Set(values)];
  const allMissing = values.every((value) => value === "Not recorded");
  if (allMissing) {
    return {
      label,
      status: "missing",
      summary: "Not recorded",
    };
  }
  if (uniqueValues.length === 1) {
    return {
      label,
      status: "match",
      summary: uniqueValues[0]!,
    };
  }
  return {
    label,
    status: "diff",
    summary: `${uniqueValues.length} values differ`,
    detail: formatPerPlatform(entries),
  };
}

function buildDateWindowField(results: DetailResult[]): ComparabilityField {
  const dates = results.map((result) => result.run_date.slice(0, 10));
  const uniqueDates = [...new Set(dates)];
  if (uniqueDates.length === 1) {
    return {
      label: "Date window",
      status: "match",
      summary: uniqueDates[0]!,
    };
  }
  const sortedDates = [...uniqueDates].sort();
  return {
    label: "Date window",
    status: "diff",
    summary: `${sortedDates[0]} to ${sortedDates[sortedDates.length - 1]}`,
    detail: formatPerPlatform(
      results.map((result) => ({
        platform: result.platform,
        value: result.run_date.slice(0, 10),
      })),
    ),
  };
}

function buildEnvironmentField(results: DetailResult[]): ComparabilityField {
  return compareValues("Environment", results, (result) => formatEnvironment(result.environment));
}

function queryCount(result: DetailResult) {
  return result.display_timings.length || new Set(result.queries.map((query) => query.query_id)).size;
}

function formatTuning(result: DetailResult) {
  // The fingerprint is built from the ADR-1 bundle-emitted identities only:
  // the canonical requested-config hash and the physical applied-ledger hash.
  // The self-derived `tuning_hash` is NOT used here -- it must stay
  // display-only and never act as a comparability key. When neither identity
  // hash exists (legacy / mode-only bundles) the coarse `tuning_mode` is shown
  // as a plain label, not dressed up as a hash-level fingerprint it isn't.
  const requestedHash = result.requested_config_hash;
  const appliedHash = result.applied_ledger_hash;
  if (!result.tuning_mode && !requestedHash && !appliedHash && !result.has_tuning) {
    return "Not recorded";
  }
  const parts = [
    result.tuning_mode ? result.tuning_mode : "Recorded",
    requestedHash ? `requested ${shortHash(requestedHash)}` : null,
    appliedHash ? `applied ${shortHash(appliedHash)}` : null,
  ].filter((part): part is string => part !== null);
  return parts.join(", ");
}

function buildTuningField(results: DetailResult[]): ComparabilityField {
  const field = compareValues("Tuning", results, formatTuning);
  if (field.status !== "diff") return field;

  const requestedHashes = results.map((result) => result.requested_config_hash);
  const appliedHashes = results.map((result) => result.applied_ledger_hash ?? null);
  const sameRecordedRequest = requestedHashes.every(Boolean) && new Set(requestedHashes).size === 1;
  const appliedStatementsDiffer = new Set(appliedHashes).size > 1;
  if (!sameRecordedRequest || !appliedStatementsDiffer) return field;

  return {
    ...field,
    summary: "Requested configuration matches; applied statements differ",
  };
}

function formatEnvironment(environment: Environment) {
  const parts = [
    environment.os,
    environment.arch,
    environment.cpu_count !== undefined ? `${environment.cpu_count} CPU` : null,
    environment.memory_gb !== undefined ? `${environment.memory_gb} GB` : null,
    environment.python ? `Python ${environment.python}` : null,
  ].filter((part): part is string => part !== null && part !== undefined && part !== "");
  return parts.length > 0 ? parts.join(", ") : "Not recorded";
}

function formatPerPlatform(entries: { platform: string; value: string }[]) {
  return entries.map((entry) => `${entry.platform}: ${entry.value}`).join("; ");
}

function valueOrMissing(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value);
}

function statusLabel(status: ComparabilityStatus) {
  if (status === "match") return "Match";
  if (status === "diff") return "Differs";
  return "Not recorded";
}

function statusTone(status: ComparabilityStatus): StatusTone {
  if (status === "match") return "success";
  if (status === "diff") return "warning";
  return "neutral";
}
