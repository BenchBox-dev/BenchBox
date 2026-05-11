// ---------------------------------------------------------------------------
// Shared display utilities
// ---------------------------------------------------------------------------

export const BENCHMARK_LABELS: Record<string, string> = {
  ai_primitives: "AI Primitives",
  amplab: "AMPLab",
  clickbench: "ClickBench",
  coffeeshop: "CoffeeShop",
  datavault: "TPC-H Data Vault",
  flightdata: "Flight Data",
  h2odb: "H2ODB",
  joinorder: "JoinOrder",
  metadata_primitives: "Metadata",
  nyctaxi: "NYC Taxi",
  read_primitives: "Read Primitives",
  star_schema: "SSB",
  ssb: "SSB",
  "tsbs-devops": "TSBS DevOps",
  tsbs_devops: "TSBS DevOps",
  tpcdi: "TPC-DI",
  tpcds: "TPC-DS",
  tpcds_obt: "TPC-DS-OBT",
  tpch: "TPC-H",
  tpch_skew: "TPC-H Skew",
  tpchavoc: "TPC-Havoc",
  transaction_primitives: "Transactions",
  vector_search: "Vector Search",
  write_primitives: "Write Primitives",
};

export function humanizeBenchmark(benchmark: string): string {
  return BENCHMARK_LABELS[benchmark] ?? benchmark.toUpperCase();
}

/** True when the slug names a benchmark family the explorer knows about,
 *  even if no rows have been ingested yet. */
export function isKnownBenchmark(benchmark: string): boolean {
  return Object.prototype.hasOwnProperty.call(BENCHMARK_LABELS, benchmark);
}

export function fmtScore(score: number | null | undefined): string {
  if (score == null) return "-";
  const abs = Math.abs(score);
  const maximumFractionDigits = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 10 ? 2 : 3;
  return score.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  });
}

export function fmtScoreExact(score: number | null | undefined): string {
  if (score == null) return "-";
  return score.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 12,
  });
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
