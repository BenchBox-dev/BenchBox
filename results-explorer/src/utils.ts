// ---------------------------------------------------------------------------
// Shared display utilities
// ---------------------------------------------------------------------------

export const BENCHMARK_LABELS: Record<string, string> = {
  tpch: "TPC-H",
  tpcds: "TPC-DS",
  ssb: "SSB",
  star_schema: "SSB",
  clickbench: "ClickBench",
  nyctaxi: "NYC Taxi",
  h2odb: "H2O DB",
  datavault: "DataVault",
};

export function humanizeBenchmark(benchmark: string): string {
  return BENCHMARK_LABELS[benchmark] ?? benchmark.toUpperCase();
}

/** True when the slug names a benchmark family the explorer knows about,
 *  even if no rows have been ingested yet. */
export function isKnownBenchmark(benchmark: string): boolean {
  return Object.prototype.hasOwnProperty.call(BENCHMARK_LABELS, benchmark);
}

export function fmtScore(score: number | null): string {
  return score !== null ? score.toLocaleString() : "-";
}

/** Format a millisecond value for display. */
export function fmtMs(ms: number): string {
  if (ms >= 10_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms.toFixed(0)} ms`;
}

/** Format a geomean_ms value, returning "N/A" for null/undefined. */
export function fmtGeomean(ms: number | null | undefined): string {
  return ms != null ? fmtMs(ms) : "N/A";
}

export function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Render the parenthetical compliance tag used next to benchmark titles.
 * Mirrors the `compliance_class` values written by the Python pipeline.
 */
export function complianceLabel(complianceClass: string | null | undefined): string {
  switch (complianceClass) {
    case "unofficial_subscale":
      return "(subscale)";
    case "unofficial_nonstandard":
      return "(non-standard)";
    default:
      return "(unofficial)";
  }
}
