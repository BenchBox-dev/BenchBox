import { canonicalBenchmarkSlug, canonicalPhase, formatBenchmarkLabel } from "@/lib/displayLabels";
import {
  basesEqual,
  formatBasisLabel,
  parseAvailableBases,
  type MeasurementBasis,
} from "@/lib/measurementBasis";

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
  /** Nullable because generic `bench.results` rows are result-level, not ranking rows. */
  primaryMetric: string | null;
  /**
   * The measurement basis in force for this comparison, or null before one is
   * locked.
   *
   * The basis belongs in the cohort signature for the same reason benchmark
   * and scale do: it is a property the whole comparison must agree on, and a
   * run that cannot answer it is not comparable here. Recording it in the lock
   * also means a shared link reproduces the cohort AND the reduction, not just
   * the cohort.
   */
  basis: MeasurementBasis | null;
}

export type CompareCohortField =
  | "benchmark"
  | "scale"
  | "phase"
  | "primary metric"
  | "measurement basis";

export interface CompareCohortRow {
  benchmark?: unknown;
  scale_factor?: unknown;
  phase?: unknown;
  test_type?: unknown;
  primary_metric?: unknown;
  /**
   * `result_basis_availability.available_bases` for this run, when the caller
   * has it. Absent means "unknown", which is treated as compatible: a snapshot
   * built before the basis columns existed must not have every row declared
   * incompatible.
   */
  available_bases?: unknown;
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

/**
 * Build the comparable-cohort signature used by Query and Platform entrypoints.
 *
 * Benchmark + scale + phase are always compared when present. When
 * `primary_metric` is available from a ranking-aware helper, it is part of the
 * lock. Plain `bench.results` workbench rows are result-level rows, so their
 * same-benchmark lock keeps the Compare page's primary metric stable through
 * the benchmark registry rather than through per-row ranking metadata.
 */
export function compareCohortSignatureForRow(
  row: CompareCohortRow,
  basis: MeasurementBasis | null = null,
): CompareCohortSignature {
  return {
    benchmark: canonicalBenchmarkSlug(asText(row.benchmark)),
    scaleFactor: asText(row.scale_factor),
    phase: canonicalPhase(asText(row.phase ?? row.test_type)),
    primaryMetric: asText(row.primary_metric) || null,
    basis,
  };
}

/**
 * Whether a run can serve the basis a cohort has locked.
 *
 * Unknown availability is compatible, not incompatible. A row that simply does
 * not carry `available_bases` -- an older snapshot, or a caller that did not
 * fetch it -- must not be filtered out of every comparison; the honest
 * response to "we do not know" is to let the value resolution report
 * unavailability per query, where it can name the reason.
 */
export function rowAnswersBasis(row: CompareCohortRow, basis: MeasurementBasis | null): boolean {
  if (basis === null) return true;
  if (row.available_bases === undefined || row.available_bases === null) return true;
  const available = parseAvailableBases(asText(row.available_bases));
  if (available.length === 0) return true;
  return available.some((candidate) => basesEqual(candidate, basis));
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
  if (!rowAnswersBasis(row, signature.basis)) mismatches.push("measurement basis");
  return mismatches;
}

export function compareCohortSummary(signature: CompareCohortSignature): string {
  const parts = [formatBenchmarkLabel(signature.benchmark)];
  if (signature.scaleFactor !== "") parts.push(`SF ${signature.scaleFactor}`);
  if (signature.phase !== "") parts.push(signature.phase);
  if (signature.basis !== null) parts.push(`at ${formatBasisLabel(signature.basis)}`);
  return parts.join(" ");
}

/**
 * Lock the single basis a cross-run comparison reads.
 *
 * The type system already makes a heterogeneous cross-run comparison
 * unrepresentable (see measurementBasis.ts). This is the same rule at the
 * runtime boundary, where bases arrive as untyped strings from a URL or from
 * user selection and a surface could otherwise assemble a list before the
 * types ever see it. Reporting it here puts it in the same place as every
 * other cohort violation, so a surface handles one kind of failure rather
 * than two.
 *
 * An empty list is not an error: nothing is locked yet.
 */
export function lockCrossRunBasis(
  bases: readonly MeasurementBasis[],
): { ok: true; basis: MeasurementBasis | null } | { ok: false; reason: string } {
  const distinct: MeasurementBasis[] = [];
  for (const basis of bases) {
    if (!distinct.some((b) => basesEqual(b, basis))) distinct.push(basis);
  }
  if (distinct.length === 0) return { ok: true, basis: null };
  if (distinct.length === 1) return { ok: true, basis: distinct[0]! };
  return {
    ok: false,
    reason:
      "A comparison across runs reads every run through one measurement basis. " +
      `This selection carries ${distinct.length}: ` +
      `${distinct.map(formatBasisLabel).join(", ")}. ` +
      "Comparing one run's basis against another's measures the basis, not the engine.",
  };
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
