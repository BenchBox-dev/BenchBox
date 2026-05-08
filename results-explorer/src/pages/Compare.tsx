import { useEffect, useRef, useState } from "preact/hooks";
import { route } from "preact-router";
import type { RoutableProps } from "preact-router";
import type { DetailResult } from "@/types";
import { getDetailResult, getPrimaryMetricForBenchmark, resolveShortId, toShortIds } from "@/lib/duckdbQueries";
import { humanizeBenchmark, errMsg, fmtGeomean } from "@/utils";
import { CompareSummarySkeleton } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge } from "@/components/TrustBadge";
import { TuningBadge } from "@/components/TuningBadge";
import { ComparabilityReceipt, buildComparabilityFields } from "@/components/ComparabilityReceipt";
import { CompareSummary } from "@/components/CompareSummary";
import { QueryDiffTable } from "@/components/QueryDiffTable";
import { modeLabel, testTypeLabel } from "@/components/MethodologyDisclosure";
import { vsSlowestRatio } from "@/lib/chartMath";
import { buildCompareDecisionSummary } from "@/lib/compareSummary";
import { paletteColor } from "@/lib/chartTheme";
import { ChartPanel } from "@/components/ChartPanel";
import { Select } from "@/components/Select";
import { StatusBadge } from "@/components/StatusBadge";
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
  const [baselineIndex, setBaselineIndex] = useState(0);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const results = compareState?.results ?? EMPTY_RESULTS;
  const primaryMetric = compareState?.primaryMetric ?? "display_geomean_ms";
  const normalizedBaselineIndex = results[baselineIndex] ? baselineIndex : 0;
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

        const metric = await getPrimaryMetricForBenchmark(details[0]!.benchmark);
        if (cancelled) return;
        setBaselineIndex(0);
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
        const params = new URLSearchParams(window.location.search);
        params.set("ids", shortIds.join(","));
        history.replaceState(null, "", `/results/compare?${params.toString()}`);
      })
      .catch(() => {
        /* silently skip - non-critical */
      });
  }, [results]);

  if (loading) return <CompareSummarySkeleton message="Loading results for comparison..." />;
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
  const severeMismatchReason = severeCohortMismatchReason(results);
  const comparabilityFields = buildComparabilityFields(results);
  const comparabilityWarningCount = comparabilityFields.filter((field) => field.status === "diff").length;
  const mixedBenchmark = new Set(results.map((result) => result.benchmark)).size > 1;
  const benchmarkLabel = mixedBenchmark ? "Mixed Benchmark" : humanizeBenchmark(benchmark);
  const scaleFactorLabel = new Set(results.map((result) => result.scale_factor)).size > 1
    ? "Mixed scale factors"
    : `SF ${scaleFactor}`;
  const rowCount = results.length;

  // Primary metric is loaded async from DuckDB in the effect above; default
  // stays `display_geomean_ms` until the query resolves (matches Python's
  // `_DEFAULT_RANKING`).
  const higherIsBetter = primaryMetric === "power_score";

  const primaries: (number | null)[] = results.map((r) =>
    primaryMetric === "power_score" ? r.power_score : r.display_geomean_ms,
  );
  const decisionSummary = buildCompareDecisionSummary(results, primaryMetric, {
    suppressWinnerClaims: severeMismatchReason !== null,
    suppressionReason: severeMismatchReason ?? undefined,
  });

  const validPrimaries = primaries.filter((v): v is number => v !== null);
  const fastestPrimary =
    validPrimaries.length > 0 ? (higherIsBetter ? Math.max(...validPrimaries) : Math.min(...validPrimaries)) : null;
  const slowestPrimary =
    validPrimaries.length > 0 ? (higherIsBetter ? Math.min(...validPrimaries) : Math.max(...validPrimaries)) : null;

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
        crumbs={
          mixedBenchmark
            ? [{ label: "Results", href: "/results/" }, { label: "Compare" }]
            : [
                { label: "Results", href: "/results/" },
                { label: benchmarkLabel, href: `/results/${benchmark}/` },
                { label: "Compare" },
              ]
        }
      />

      <section class="mt-6 mb-8 panel-elevated p-5" aria-label="Comparison summary">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-subtle)]">Compare</p>
            <h1 class="mt-1 text-3xl font-bold text-[var(--bb-data-fg-primary)]">{benchmarkLabel} Comparison</h1>
            <p class="mt-1 text-sm text-[var(--bb-data-fg-muted)]">
              Scale factor: {scaleFactorLabel} - {rowCount} platforms
            </p>
            {/* Trust tier diversity note - informational, not a warning */}
            {(() => {
              const tiers = [...new Set(rowData.map((r) => r.trustLabel))];
              return tiers.length > 1 ? (
                <p class="mt-1 text-xs text-[var(--bb-data-fg-subtle)]">Comparing across trust tiers: {tiers.join(", ")}</p>
              ) : null;
            })()}
          </div>
          <button class="btn btn-secondary" onClick={handleShare}>
            {copied ? "Copied!" : "Share URL"}
          </button>
        </div>
      </section>

      <CompareGuardrailSummary warningCount={comparabilityWarningCount} severeMismatchReason={severeMismatchReason} />
      <CompareSummary summary={decisionSummary} />
      {results.length > 1 && (
        <div class="panel mb-4 flex flex-wrap items-center justify-between gap-3 px-3 py-2 shadow-sm">
          <div>
            <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="compare-baseline">
              Baseline
            </label>
            <p class="text-xs text-[var(--bb-data-fg-muted)]">Ratios and deltas compare every candidate against this run.</p>
          </div>
          <Select
            id="compare-baseline"
            ariaLabel="Baseline"
            value={String(normalizedBaselineIndex)}
            onChange={(value) => setBaselineIndex(Number(value))}
            options={results.map((result, index) => ({ value: String(index), label: result.platform }))}
            size="sm"
          />
        </div>
      )}

      {rowCount > 0 && (
        <div class="mb-8">
          <ChartPanel
            context={{ kind: "compare", results, primaryMetric }}
            baselineIndex={normalizedBaselineIndex}
            onBaselineIndexChange={setBaselineIndex}
            suppressWinnerClaims={severeMismatchReason !== null}
            suppressionReason={severeMismatchReason ?? undefined}
          />
        </div>
      )}

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
          const showPrimaryClaims = severeMismatchReason === null;
          const isFastest =
            showPrimaryClaims && primary !== null && fastestPrimary !== null && primary === fastestPrimary;

          return (
            <div
              key={r.resultId}
              class="card relative overflow-hidden"
              style={{ borderTopColor: color, borderTopWidth: "3px" }}
            >
              <div class="mb-2 flex items-center justify-between">
                <span class="font-semibold text-[var(--bb-data-fg-primary)]">{r.label}</span>
                <div class="flex flex-wrap gap-1">
                  <TrustBadge trustLabel={r.trustLabel} compact />
                  {r.tuningMode && <TuningBadge tuningMode={r.tuningMode} />}
                  {isFastest && <StatusBadge role="ranking" tone="success">fastest</StatusBadge>}
                </div>
              </div>
              <p class="mb-3 text-xs text-[var(--bb-data-fg-muted)]">
                {r.runDate.slice(0, 10)}
                {r.driverVersion && !r.label.includes(`v${r.driverVersion}`) && ` · v${r.driverVersion}`}
              </p>
              <dl class="space-y-1 text-sm">
                <div class="flex justify-between">
                  <dt class="text-[var(--bb-data-fg-muted)]">
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
                    <dt class="text-xs text-[var(--bb-data-fg-muted)]">Geomean</dt>
                    <dd class="font-mono text-xs text-[var(--bb-data-fg-muted)]">{fmtGeomean(r.displayGeomeanMs)}</dd>
                  </div>
                )}
                {r.totalDurationS !== null && (
                  <div class="flex justify-between">
                    <dt class="text-[var(--bb-data-fg-muted)]">Wall-clock total</dt>
                    <dd class="font-mono text-[var(--bb-data-fg-primary)]">{r.totalDurationS.toFixed(2)}s</dd>
                  </div>
                )}
                {showPrimaryClaims && speedup !== null && (
                  <div class="flex justify-between">
                    <dt class="text-[var(--bb-data-fg-muted)]">{vsLabel}</dt>
                    <dd class="font-mono">{speedup.toFixed(2)}x</dd>
                  </div>
                )}
                {r.executionMode && (
                  <div class="flex justify-between">
                    <dt class="text-[var(--bb-data-fg-muted)]">Mode</dt>
                    <dd class="text-[var(--bb-data-fg-primary)]">{modeLabel(r.executionMode)}</dd>
                  </div>
                )}
                {r.testType && (
                  <div class="flex justify-between">
                    <dt class="text-[var(--bb-data-fg-muted)]">Test type</dt>
                    <dd class="text-[var(--bb-data-fg-primary)]">{testTypeLabel(r.testType)}</dd>
                  </div>
                )}
              </dl>
              <a
                href={`/results/r/${r.resultId}`}
                class="mt-3 block text-xs no-underline text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-accent-hover)]"
              >
                View detail →
              </a>
            </div>
          );
        })}
      </div>

      <p class="mb-6 text-xs text-[var(--bb-data-fg-subtle)]">
        <strong>Geomean query time</strong> - geometric mean of per-query execution times (measurement runs only). More
        comparable than wall-clock total when query counts differ. Lower is faster.
      </p>

      <QueryDiffTable
        results={results}
        baselineIndex={normalizedBaselineIndex}
        suppressionReason={severeMismatchReason}
      />
      <ComparabilityReceipt results={results} />
    </div>
  );
}

function CompareGuardrailSummary({
  warningCount,
  severeMismatchReason,
}: {
  warningCount: number;
  severeMismatchReason: string | null;
}) {
  const hasSevereMismatch = severeMismatchReason !== null;
  return (
    <section aria-label="Compare guardrails" class="mb-4 panel-elevated p-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">Comparability guardrails</h2>
          <p class="mt-1 text-sm text-[var(--bb-data-fg-muted)]">
            {hasSevereMismatch
              ? `Winner claims are suppressed because ${severeMismatchReason}.`
              : "Selected runs share the same benchmark and scale for winner claims."}
          </p>
        </div>
        <StatusBadge
          role="comparison"
          tone={hasSevereMismatch || warningCount > 0 ? "warning" : "success"}
        >
          {hasSevereMismatch ? "Claims suppressed" : warningCount > 0 ? `${warningCount} warnings` : "Comparable"}
        </StatusBadge>
      </div>
    </section>
  );
}

function severeCohortMismatchReason(results: DetailResult[]) {
  const reasons: string[] = [];
  if (new Set(results.map((result) => result.benchmark)).size > 1) {
    reasons.push("benchmarks differ");
  }
  if (new Set(results.map((result) => result.scale_factor)).size > 1) {
    reasons.push("scale factors differ");
  }
  return reasons.length > 0 ? reasons.join(" and ") : null;
}
