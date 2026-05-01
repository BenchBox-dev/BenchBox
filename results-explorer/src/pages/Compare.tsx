import { useEffect, useRef, useState } from "preact/hooks";
import { route } from "preact-router";
import type { RoutableProps } from "preact-router";
import type { DetailResult } from "@/types";
import { getDetailResult, getPrimaryMetricForBenchmark, resolveShortId, toShortIds } from "@/lib/duckdbQueries";
import { humanizeBenchmark, errMsg, fmtGeomean } from "@/utils";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge } from "@/components/TrustBadge";
import { TuningBadge } from "@/components/TuningBadge";
import { ComparabilityBanner, buildComparabilityWarnings } from "@/components/ComparabilityBanner";
import { modeLabel, testTypeLabel } from "@/components/MethodologyDisclosure";
import { perQuerySpeedup, vsSlowestRatio } from "@/lib/chartMath";
import { paletteColor } from "@/lib/chartTheme";
import { ChartPanel } from "@/components/ChartPanel";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

type PrimaryMetric = "power_score" | "display_geomean_ms";
interface CompareState {
  results: DetailResult[];
  primaryMetric: PrimaryMetric;
}

const EMPTY_RESULTS: DetailResult[] = [];

export function Compare(_: RoutableProps) {
  const [compareState, setCompareState] = useState<CompareState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const results = compareState?.results ?? EMPTY_RESULTS;
  const primaryMetric = compareState?.primaryMetric ?? "display_geomean_ms";
  useDocumentTitle(
    results.length > 0 ? `Compare (${results.length}) · BenchBox Results` : "Compare · BenchBox Results",
  );
  useEffect(() => {
    let cancelled = false;

    const params = new URLSearchParams(window.location.search);
    const idsParam = params.get("ids") ?? "";
    const ids = idsParam
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 4);

    if (ids.length === 0) {
      setError("No result IDs provided. Add ?ids=id1,id2 to the URL.");
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }

    if (ids.length === 1) {
      resolveShortId(ids[0]!)
        .then(async (resolvedId) => {
          if (cancelled) return;
          const detail = await getDetailResult(resolvedId);
          if (cancelled) return;
          if (detail === null) {
            setError(
              `No result found for: ${resolvedId}. ` +
                "These results may have been removed from the published dataset.",
            );
            setLoading(false);
            return;
          }
          route(`/results/r/${encodeURIComponent(resolvedId)}`, true);
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setError(errMsg(err));
            setLoading(false);
          }
        });
      return () => {
        cancelled = true;
      };
    }

    Promise.all(ids.map((id) => resolveShortId(id)))
      .then(async (resolvedIds) => {
        if (cancelled) return;

        const loaded = await Promise.all(resolvedIds.map((id) => getDetailResult(id)));
        if (cancelled) return;

        const missing = resolvedIds.filter((_, i) => loaded[i] === null);
        if (missing.length > 0) {
          setError(
            `No result found for: ${missing.join(", ")}. ` +
              "These results may have been removed from the published dataset.",
          );
          setLoading(false);
          return;
        }
        const details = loaded as DetailResult[];

        const benchmarkSet = new Set(details.map((r) => r.benchmark));
        const scaleSet = new Set(details.map((r) => r.scale_factor));

        if (benchmarkSet.size > 1) {
          setError(
            `Cannot compare results from different benchmarks: ${[...benchmarkSet].join(", ")}. ` +
              "All results in a comparison must use the same benchmark.",
          );
          setLoading(false);
          return;
        }

        if (scaleSet.size > 1) {
          setError(
            `Cannot compare results at different scale factors: ${[...scaleSet].join(", ")}. ` +
              "All results in a comparison must use the same scale factor.",
          );
          setLoading(false);
          return;
        }

        const metric = await getPrimaryMetricForBenchmark(details[0]!.benchmark);
        if (cancelled) return;
        setCompareState({ results: details, primaryMetric: metric });
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(errMsg(err));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
      if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current);
    };
  }, []);

  // Canonicalize URL to short IDs once data is loaded and URL has long-form IDs.
  useEffect(() => {
    const ids = results.map((r) => r.result_id);
    if (ids.length === 0) return;
    const raw = new URLSearchParams(window.location.search).get("ids") ?? "";
    const hasLongForm = raw.split(",").some((id) => id.trim().includes("-"));
    if (!hasLongForm) return;
    toShortIds(ids)
      .then((shortIds) => {
        history.replaceState(null, "", `/results/compare?ids=${shortIds.join(",")}`);
      })
      .catch(() => {
        /* silently skip - non-critical */
      });
  }, [results]);

  if (loading) return <LoadingSpinner message="Loading results for comparison..." />;
  if (error)
    return (
      <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <ErrorMessage title="Cannot compare" message={error} />
        <a href="/results/" class="mt-4 inline-block text-sm no-underline">
          ← Back to Results
        </a>
      </div>
    );

  if (results.length === 0) return null;

  const benchmark = results[0]?.benchmark ?? "";
  const scaleFactor = results[0]?.scale_factor ?? 0;
  const benchmarkLabel = humanizeBenchmark(benchmark);
  const rowCount = results.length;

  // Union of query IDs in natural sort order.
  const allQueryIds: string[] = [...new Set(results.flatMap((r) => r.display_timings.map((t) => t.query_id)))].sort(
    (a, b) => a.localeCompare(b, undefined, { numeric: true }),
  );

  // Per-query timing data consumed by chart components (ms values). The
  // pipeline pre-computes a median-of-passing-measurement-runs `display_ms`
  // for every (result, query) pair and we read it verbatim - no TS-side
  // reduction.
  const queryTimingData = allQueryIds.map((queryId) => ({
    queryId,
    timings: results.map((r) => {
      const ms = r.display_timings.find((t) => t.query_id === queryId)?.display_ms ?? null;
      return ms !== null ? { ms, status: "pass" } : null;
    }),
  }));

  // Primary metric is loaded async from DuckDB in the effect above; default
  // stays `display_geomean_ms` until the query resolves (matches Python's
  // `_DEFAULT_RANKING`).
  const higherIsBetter = primaryMetric === "power_score";

  const primaries: (number | null)[] = results.map((r) =>
    primaryMetric === "power_score" ? r.power_score : r.display_geomean_ms,
  );

  const validPrimaries = primaries.filter((v): v is number => v !== null);
  const fastestPrimary =
    validPrimaries.length > 0 ? (higherIsBetter ? Math.max(...validPrimaries) : Math.min(...validPrimaries)) : null;
  const slowestPrimary =
    validPrimaries.length > 0 ? (higherIsBetter ? Math.min(...validPrimaries) : Math.max(...validPrimaries)) : null;

  const comparabilityWarnings = buildComparabilityWarnings(
    results.map((r) => ({
      platform: r.platform,
      execution_mode: r.execution_mode,
      tuning_mode: r.tuning_mode,
      test_type: r.test_type,
      query_count: r.queries.length,
    })),
  );

  const rowData = results.map((r) => ({
    resultId: r.result_id,
    label: r.platform,
    trustLabel: r.trust_label,
    runDate: r.run_date,
    tuningMode: r.tuning_mode,
    executionMode: r.execution_mode,
    testType: r.test_type,
    powerScore: r.power_score,
    displayGeomeanMs: r.display_geomean_ms,
    totalDurationS: r.total_duration_s,
    driverVersion: r.driver_version,
  }));

  function handleShare() {
    navigator.clipboard
      .writeText(window.location.href)
      .then(() => {
        setCopied(true);
        copyTimerRef.current = setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        /* clipboard not available */
      });
  }

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Breadcrumb
        crumbs={[
          { label: "Results", href: "/results/" },
          { label: benchmarkLabel, href: `/results/${benchmark}/` },
          { label: "Compare" },
        ]}
      />

      <div class="mt-6 mb-8 flex items-center justify-between">
        <div>
          <h1 class="text-3xl font-bold text-gray-900">{benchmarkLabel} Comparison</h1>
          <p class="mt-1 text-sm text-gray-500">
            Scale factor: SF {scaleFactor} - {rowCount} platforms
          </p>
          {/* Trust tier diversity note - informational, not a warning */}
          {(() => {
            const tiers = [...new Set(rowData.map((r) => r.trustLabel))];
            return tiers.length > 1 ? (
              <p class="mt-1 text-xs text-gray-400">Comparing across trust tiers: {tiers.join(", ")}</p>
            ) : null;
          })()}
        </div>
        <button class="btn btn-secondary" onClick={handleShare}>
          {copied ? "Copied!" : "Share URL"}
        </button>
      </div>

      <ComparabilityBanner warnings={comparabilityWarnings} />

      <div class="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {rowData.map((r, i) => {
          const color = paletteColor(i);
          const primary = primaries[i] ?? null;
          // For latency metrics (lower-is-better): ratio = slowest / this (≥1)
          // For score metrics (higher-is-better): ratio = this / worst (≥1)
          const speedup = higherIsBetter
            ? primary !== null && slowestPrimary !== null && slowestPrimary > 0
              ? primary / slowestPrimary
              : null
            : vsSlowestRatio(primary, slowestPrimary);
          const vsLabel = higherIsBetter ? "vs worst" : "vs slowest";
          const isFastest = primary !== null && fastestPrimary !== null && primary === fastestPrimary;

          return (
            <div
              key={r.resultId}
              class="card relative overflow-hidden"
              style={{ borderTopColor: color, borderTopWidth: "3px" }}
            >
              <div class="mb-2 flex items-center justify-between">
                <span class="font-semibold text-gray-900">{r.label}</span>
                <div class="flex flex-wrap gap-1">
                  <TrustBadge trustLabel={r.trustLabel} compact />
                  {r.tuningMode && <TuningBadge tuningMode={r.tuningMode} />}
                  {isFastest && <span class="badge badge-green">fastest</span>}
                </div>
              </div>
              <p class="text-xs text-gray-500 mb-3">
                {r.runDate.slice(0, 10)}
                {r.driverVersion && !r.label.includes(`v${r.driverVersion}`) && ` · v${r.driverVersion}`}
              </p>
              <dl class="space-y-1 text-sm">
                <div class="flex justify-between">
                  <dt class="text-gray-500">
                    {primaryMetric === "power_score" ? "Power score" : "Geomean query time"}
                  </dt>
                  <dd class="font-mono font-medium">
                    {primaryMetric === "power_score"
                      ? r.powerScore !== null
                        ? r.powerScore.toLocaleString()
                        : "-"
                      : fmtGeomean(r.displayGeomeanMs)}
                  </dd>
                </div>
                {primaryMetric === "power_score" && (
                  <div class="flex justify-between">
                    <dt class="text-gray-500 text-xs">Geomean</dt>
                    <dd class="font-mono text-gray-500 text-xs">{fmtGeomean(r.displayGeomeanMs)}</dd>
                  </div>
                )}
                {r.totalDurationS !== null && (
                  <div class="flex justify-between">
                    <dt class="text-gray-500">Wall-clock total</dt>
                    <dd class="font-mono text-gray-600">{r.totalDurationS.toFixed(2)}s</dd>
                  </div>
                )}
                {speedup !== null && (
                  <div class="flex justify-between">
                    <dt class="text-gray-500">{vsLabel}</dt>
                    <dd class="font-mono">{speedup.toFixed(2)}x</dd>
                  </div>
                )}
                {r.executionMode && (
                  <div class="flex justify-between">
                    <dt class="text-gray-500">Mode</dt>
                    <dd class="text-gray-700">{modeLabel(r.executionMode)}</dd>
                  </div>
                )}
                {r.testType && (
                  <div class="flex justify-between">
                    <dt class="text-gray-500">Test type</dt>
                    <dd class="text-gray-700">{testTypeLabel(r.testType)}</dd>
                  </div>
                )}
              </dl>
              <a
                href={`/results/r/${r.resultId}`}
                class="mt-3 block text-xs no-underline text-gray-400 hover:text-gray-600"
              >
                View detail →
              </a>
            </div>
          );
        })}
      </div>

      <p class="mb-6 text-xs text-gray-400">
        <strong>Geomean query time</strong> - geometric mean of per-query execution times (measurement runs only). More
        comparable than wall-clock total when query counts differ. Lower is faster.
      </p>

      {rowCount > 0 && (
        <div class="mb-8">
          <ChartPanel context={{ kind: "compare", results, primaryMetric }} />
        </div>
      )}

      <section class="card">
        <h2 class="mb-4 text-base font-semibold text-gray-900">Query Breakdown</h2>
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
              <tr>
                <th class="table-th">Query</th>
                {rowData.map((r) => (
                  <th key={r.resultId} class="table-th">
                    {r.label}
                  </th>
                ))}
                <th class="table-th">Δ fastest</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100 bg-white">
              {queryTimingData.map(({ queryId, timings }) => {
                const validMs = timings
                  .filter((t): t is NonNullable<typeof t> => t !== null && t.ms > 0)
                  .map((t) => t.ms);
                const fastest = validMs.length > 0 ? Math.min(...validMs) : null;
                const speedup = perQuerySpeedup(validMs);

                return (
                  <tr key={queryId} class="hover:bg-gray-50">
                    <td class="table-td font-mono font-medium">{queryId}</td>
                    {timings.map((t, i) => (
                      <td key={rowData[i]!.resultId} class="table-td font-mono">
                        {t === null ? (
                          <span class="text-gray-400">-</span>
                        ) : (
                          <span
                            class={
                              t.status === "fail"
                                ? "text-red-600"
                                : t.ms === fastest
                                  ? "font-semibold text-green-700"
                                  : ""
                            }
                          >
                            {t.ms.toFixed(1)}
                          </span>
                        )}
                      </td>
                    ))}
                    <td class="table-td font-mono text-gray-500">
                      {speedup !== null ? `${speedup.toFixed(2)}x` : "-"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
