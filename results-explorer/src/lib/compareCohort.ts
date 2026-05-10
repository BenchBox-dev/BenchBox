import { formatBenchmarkLabel } from "@/lib/displayLabels";

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
