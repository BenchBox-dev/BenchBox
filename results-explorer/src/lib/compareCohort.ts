import { formatBenchmarkLabel } from "@/lib/displayLabels";

/**
 * Extract the trailing short-hash token from a result id for a11y disambiguation.
 * Result IDs follow `<benchmark>-<platform>-sf<scale>-<date>-<shorthash>`; the
 * trailing token is the unique fingerprint that distinguishes otherwise-similar
 * runs. Strings without a `-` are returned as-is so callers can pass already-short
 * ids without surprise.
 */
function compareSelectionShortId(id: string): string {
  if (id.length === 0) return "";
  const trailing = id.split("-").pop()!;
  return trailing.length > 0 ? trailing : id;
}

export interface CompareCohortSignature {
  benchmark: string;
  scaleFactor: string;
  phase: string;
  /** Optional because generic `bench.results` rows may not carry ranking metadata. */
  primaryMetric: string | null;
}

export type CompareCohortField = "benchmark" | "scale" | "phase" | "primary metric";

export interface CompareCohortRow {
  benchmark?: unknown;
  scale_factor?: unknown;
  phase?: unknown;
  test_type?: unknown;
  primary_metric?: unknown;
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

/**
 * Build the comparable-cohort signature used by Query and Platform entrypoints.
 *
 * Benchmark + scale + phase are always compared when present. `primary_metric`
 * is compared only when both rows expose it; Query Workbench rows come from
 * `bench.results`, whose older schemas do not carry ranking metadata. In that
 * case the same-benchmark lock is still enough to keep the Compare page's
 * primary metric stable because it is resolved from the benchmark registry.
 */
export function compareCohortSignatureForRow(row: CompareCohortRow): CompareCohortSignature {
  return {
    benchmark: asText(row.benchmark),
    scaleFactor: asText(row.scale_factor),
    phase: asText(row.phase ?? row.test_type),
    primaryMetric: asText(row.primary_metric) || null,
  };
}

export function compareCohortMismatches(
  row: CompareCohortRow,
  signature: CompareCohortSignature,
): CompareCohortField[] {
  const candidate = compareCohortSignatureForRow(row);
  const mismatches: CompareCohortField[] = [];
  if (candidate.benchmark !== signature.benchmark) mismatches.push("benchmark");
  if (candidate.scaleFactor !== signature.scaleFactor) mismatches.push("scale");
  if (candidate.phase !== signature.phase) mismatches.push("phase");
  if (
    signature.primaryMetric !== null &&
    candidate.primaryMetric !== null &&
    candidate.primaryMetric !== signature.primaryMetric
  ) {
    mismatches.push("primary metric");
  }
  return mismatches;
}

export function compareCohortSummary(signature: CompareCohortSignature): string {
  const parts = [formatBenchmarkLabel(signature.benchmark)];
  if (signature.scaleFactor !== "") parts.push(`SF ${signature.scaleFactor}`);
  if (signature.phase !== "") parts.push(signature.phase);
  return parts.join(" ");
}

export function compareCohortLockReason(
  row: CompareCohortRow,
  signature: CompareCohortSignature | null,
): string | undefined {
  if (signature === null) return undefined;
  const mismatches = compareCohortMismatches(row, signature);
  if (mismatches.length === 0) return undefined;
  return (
    `Locked: first selection is ${compareCohortSummary(signature)}. ` +
    `This row differs by ${mismatches.join(", ")}.`
  );
}

/**
 * Stable partition of rows into `{compatible, incompatible}` against a locked
 * cohort signature. Used by Compare and Query Workbench so compatible
 * candidates surface above incompatibles after the first selection,
 * regardless of the user's column-sort choice.
 *
 * Stability: relative order within each bucket matches the input order. When
 * `signature` is null (no selection yet) every row is treated as compatible.
 */
export function compareCohortPartition<T extends CompareCohortRow>(
  rows: readonly T[],
  signature: CompareCohortSignature | null,
): { compatible: T[]; incompatible: T[] } {
  if (signature === null) return { compatible: [...rows], incompatible: [] };
  const compatible: T[] = [];
  const incompatible: T[] = [];
  for (const row of rows) {
    if (compareCohortMismatches(row, signature).length === 0) compatible.push(row);
    else incompatible.push(row);
  }
  return { compatible, incompatible };
}

/**
 * Build a disambiguated accessible name for compare-selection checkboxes.
 * Repeated platform names ("Select DuckDB for comparison" five times) are
 * indistinguishable to assistive technology and locator-driven tests; this
 * helper appends benchmark, scale, phase, run date, and a short result-id
 * suffix so each row has a unique accessible name.
 */
export interface CompareSelectionLabelInput {
  platform?: string | null;
  benchmark?: string | null;
  scaleFactor?: string | number | null;
  phase?: string | null;
  runDate?: string | null;
  resultId?: string | null;
}

/**
 * Suffix for status copy when a cohort lock hides incompatible rows.
 * Returns an empty string for `count <= 0` so callers can append unconditionally.
 */
export function hiddenIncompatibleSuffix(count: number): string {
  if (count <= 0) return "";
  return ` ${count} incompatible row${count === 1 ? "" : "s"} hidden.`;
}

export function compareSelectionLabel(input: CompareSelectionLabelInput): string {
  const parts: string[] = [];
  const platform = (input.platform ?? "").toString().trim();
  const benchmark = (input.benchmark ?? "").toString().trim();
  const scale =
    input.scaleFactor === null || input.scaleFactor === undefined ? "" : String(input.scaleFactor).trim();
  const phase = (input.phase ?? "").toString().trim();
  const runDate = (input.runDate ?? "").toString().slice(0, 10);
  const resultId = (input.resultId ?? "").toString().trim();

  if (platform !== "") parts.push(platform);
  if (benchmark !== "") parts.push(formatBenchmarkLabel(benchmark));
  if (scale !== "") parts.push(`SF ${scale}`);
  if (phase !== "") parts.push(phase);
  if (runDate !== "") parts.push(runDate);
  if (resultId !== "") parts.push(`(${compareSelectionShortId(resultId)})`);

  if (parts.length === 0) return "Select run for comparison";
  return `Select ${parts.join(" ")} for comparison`;
}
