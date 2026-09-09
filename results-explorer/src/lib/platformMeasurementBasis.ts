import type { DetailResult } from "@/types";
import type { PlatformIndexRowRow } from "@/lib/duckdbQueries";
import { isDefaultBasis, resolveResultsForBasis, type MeasurementBasis } from "@/lib/measurementBasis";

/** A platform index spans workloads. Reduce each run over its own queries. */
export function platformRowsForBasis(
  rows: readonly PlatformIndexRowRow[],
  details: ReadonlyMap<string, DetailResult>,
  basis: MeasurementBasis,
): PlatformIndexRowRow[] {
  if (isDefaultBasis(basis)) return [...rows];
  return rows.map((row) => {
    const detail = details.get(row.result_id);
    const resolved = detail ? resolveResultsForBasis([detail], basis)[0] : undefined;
    return {
      ...row,
      geomean_ms: resolved?.display_geomean_ms ?? null,
      display_geomean_ms: resolved?.display_geomean_ms ?? null,
      // Published power incorporates more than query latency and cannot be
      // recomputed from these execution rows alone.
      power_score: null,
      primary_metric: "display_geomean_ms",
    };
  });
}
