import type { DetailResult, Environment } from "@/types";
import { humanizeBenchmark } from "@/utils";
import { costModelSummary, costScopeSummary, normalizedCostLabel } from "@/lib/costDisplay";
import { formatCount, formatWarningCount } from "@/lib/copyFormatters";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";

interface ComparabilityReceiptProps {
  results: DetailResult[];
}

type ComparabilityStatus = "match" | "diff" | "missing";

export interface ComparabilityField {
  label: string;
  status: ComparabilityStatus;
  summary: string;
  detail?: string;
}

export function ComparabilityReceipt({ results }: ComparabilityReceiptProps) {
  if (results.length === 0) return null;

  const fields = buildComparabilityFields(results);
  const warningCount = fields.filter((field) => field.status === "diff").length;

  return (
    <section id="comparability-receipt" aria-label="Comparability receipt" class="panel-elevated mb-8 p-4">
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

  return [
    compareValues("Benchmark", results, (result) => humanizeBenchmark(result.benchmark)),
    compareValues("Scale factor", results, (result) => `SF ${result.scale_factor}`),
    compareValues("Phase", results, (result) => valueOrMissing(result.test_type)),
    compareValues("Query scope", results, (result) => formatCount(queryCount(result), "query", "queries")),
    buildDateWindowField(results),
    compareValues("Platform version", results, (result) => valueOrMissing(result.platform_version)),
    compareValues("Driver version", results, (result) => valueOrMissing(result.driver_version)),
    compareValues("Execution mode", results, (result) => valueOrMissing(result.execution_mode)),
    compareValues("Tuning", results, formatTuning),
    compareValues("Validation", results, (result) => valueOrMissing(result.validation_status)),
    buildEnvironmentField(results),
    compareValues("Normalized cost", results, normalizedCostLabel),
    compareValues("Cost model", results, costModelSummary),
    compareValues("Cost scope", results, costScopeSummary),
  ];
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
  if (!result.tuning_mode && !result.tuning_hash && !result.has_tuning) return "Not recorded";
  const parts = [
    result.tuning_mode ? result.tuning_mode : "Recorded",
    result.tuning_hash ? `hash ${result.tuning_hash}` : null,
  ].filter((part): part is string => part !== null);
  return parts.join(", ");
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
