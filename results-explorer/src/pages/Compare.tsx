import type { JSX } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { route } from "preact-router";
import type { RoutableProps } from "preact-router";
import type { DetailResult } from "@/types";
import {
  getDetailResult,
  getPrimaryMetricForBenchmark,
  listResults,
  resolveShortId,
  toShortIds,
  type ResultRow,
} from "@/lib/duckdbQueries";
import { humanizeBenchmark, errMsg, fmtGeomean } from "@/utils";
import { formatBenchmarkLabel } from "@/lib/displayLabels";
import { buildCompareUrl, MAX_COMPARE_SELECTIONS } from "@/lib/resultLinks";
import {
  compareCohortLockReason,
  compareCohortMismatches,
  compareCohortPartition,
  compareCohortSignatureForRow,
  compareSelectionLabel,
  hiddenIncompatibleSuffix,
  type CompareCohortSignature,
} from "@/lib/compareCohort";
import { formatRunIdentitiesForCohort, type RunIdentitySource } from "@/lib/runIdentity";
import { CompareSummarySkeleton } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge } from "@/components/TrustBadge";
import { TuningBadge } from "@/components/TuningBadge";
import {
  COMPARABILITY_RECEIPT_ID,
  COMPARABILITY_WARNING_TARGET_ID,
  ComparabilityReceipt,
  buildComparabilityFields,
  comparabilityWarningFields,
} from "@/components/ComparabilityReceipt";
import { CompareSummary } from "@/components/CompareSummary";
import { QueryDiffTable } from "@/components/QueryDiffTable";
import { modeLabel, testTypeLabel } from "@/components/MethodologyDisclosure";
import { vsSlowestRatio } from "@/lib/chartMath";
import { buildCompareDecisionSummary } from "@/lib/compareSummary";
import { formatDurationSeconds, formatPowerScore, formatSpeedup } from "@/lib/metricFormatters";
import { isValidTimingValue } from "@/lib/displayEligibility";
import {
  describeCompareExclusionReason,
  summarizeCompareExclusionReasons,
  type CompareExclusionReasonCopy,
} from "@/lib/compareExclusionReasons";
import {
  formatCandidateCount,
  formatCount,
  formatSelectedCount,
  formatWarningClassSummary,
  formatWarningCount,
} from "@/lib/copyFormatters";
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

interface CompareProps extends RoutableProps {
  url?: string;
}

function currentCompareUrl(url: string | undefined): string {
  if (url) return url;
  if (typeof window === "undefined") return "/results/compare";
  return `${window.location.pathname}${window.location.search}`;
}

function searchParamsFromUrl(url: string): URLSearchParams {
  return new URL(url, "https://benchbox.dev").searchParams;
}

export function Compare({ url }: CompareProps) {
  const activeUrl = currentCompareUrl(url);
  const [compareState, setCompareState] = useState<CompareState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [baselineIndex, setBaselineIndex] = useState(0);
  // Builder mode: rendered when 0 ids are supplied, or when 1 id is supplied
  // (single-result entry from ResultDetail "Compare this result" button).
  // Was previously an error string ("No result IDs provided. Add ?ids=...")
  // or a silent redirect back to ResultDetail; both forced URL editing or
  // dead-ended the user on the page they came from.
  const [builderPinnedId, setBuilderPinnedId] = useState<string | null>(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const results = compareState?.results ?? EMPTY_RESULTS;
  const primaryMetric = compareState?.primaryMetric ?? "display_geomean_ms";
  const normalizedBaselineIndex = results[baselineIndex] ? baselineIndex : 0;
  useDocumentTitle(
    results.length > 0 ? `Compare (${results.length}) · BenchBox Results` : "Compare · BenchBox Results",
  );
  useEffect(() => {
    let cancelled = false;

    setCompareState(null);
    setError(null);
    setLoading(true);
    setBuilderPinnedId(null);
    setShowBuilder(false);

    const params = searchParamsFromUrl(activeUrl);
    const idsParam = params.get("ids") ?? "";
    const ids = idsParam
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 4);

    if (ids.length === 0) {
      setShowBuilder(true);
      setBuilderPinnedId(null);
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
          // Pin this run in the builder rather than redirecting back to
          // ResultDetail. The user clicked "Compare this result"; the
          // expected outcome is a comparison surface, not the page they
          // came from.
          setBuilderPinnedId(resolvedId);
          setShowBuilder(true);
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
        setShowBuilder(false);
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
  }, [activeUrl]);

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

  if (showBuilder) {
    return <CompareBuilder pinnedId={builderPinnedId} />;
  }

  if (results.length === 0) return null;

  const benchmark = results[0]?.benchmark ?? "";
  const scaleFactor = results[0]?.scale_factor ?? 0;
  const severeMismatchReason = severeCohortMismatchReason(results);
  const comparabilityFields = buildComparabilityFields(results);
  const comparabilityWarnings = comparabilityWarningFields(comparabilityFields);
  const comparabilityWarningCount = comparabilityWarnings.length;
  const comparabilityWarningLabels = comparabilityWarnings.map((field) => field.label);
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
  // Cohort-aware run identity labels for the decision summary headline +
  // winner card (finding #8). Using `formatRunIdentitiesForCohort` here means
  // that two same-platform runs (e.g. two Polars v1.40.0 from different
  // dates) get a unique label like "Polars 2026-05-02 (0093bb7a)" instead
  // of the bare "Polars" that appears in the bug report.
  const summaryRunLabels: Record<string, string> = (() => {
    const labels = formatRunIdentitiesForCohort(
      results.map((r) => ({
        result_id: r.result_id,
        platform: r.platform,
        platform_version: r.platform_version,
        driver_version: r.driver_version,
        run_date: r.run_date,
        scale_factor: r.scale_factor,
        trust_label: r.trust_label,
      })),
      "compact",
    );
    const out: Record<string, string> = {};
    results.forEach((r, i) => {
      out[r.result_id] = labels[i] ?? r.platform;
    });
    return out;
  })();
  const decisionSummary = buildCompareDecisionSummary(results, primaryMetric, {
    suppressWinnerClaims: severeMismatchReason !== null,
    suppressionReason: severeMismatchReason ?? undefined,
    runLabels: summaryRunLabels,
  });

  const validPrimaries = primaries.filter(isValidTimingValue);
  const fastestPrimary =
    validPrimaries.length > 0 ? (higherIsBetter ? Math.max(...validPrimaries) : Math.min(...validPrimaries)) : null;
  const slowestPrimary =
    validPrimaries.length > 0 ? (higherIsBetter ? Math.min(...validPrimaries) : Math.max(...validPrimaries)) : null;

  // Cohort-aware run identity labels. When the comparison includes
  // multiple runs of the same platform (e.g., DataFusion v44 vs v53,
  // or two PySpark runs from different dates), this disambiguates them
  // with the shortest qualifier suffix that makes the cohort unique.
  // Singletons keep the bare platform name.
  const identitySources: RunIdentitySource[] = results.map((r) => ({
    result_id: r.result_id,
    platform: r.platform,
    platform_version: r.platform_version,
    driver_version: r.driver_version,
    run_date: r.run_date,
    scale_factor: r.scale_factor,
    trust_label: r.trust_label,
  }));
  const cohortIdentities = formatRunIdentitiesForCohort(identitySources, "table");
  const cohortIdentitiesCompact = formatRunIdentitiesForCohort(identitySources, "compact");

  const rowData = results.map((r, idx) => ({
    resultId: r.result_id,
    label: cohortIdentities[idx]!,
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
              Scale factor: {scaleFactorLabel} - {rowCount}{" "}
              {new Set(results.map((r) => r.platform)).size === results.length ? "platforms" : "runs"}
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

      <CompareGuardrailSummary
        warningCount={comparabilityWarningCount}
        warningLabels={comparabilityWarningLabels}
        claimSuppressed={decisionSummary.claimSuppressed}
        suppressionReason={decisionSummary.claimSuppressionReason}
      />
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
            options={results.map((_result, index) => ({
              value: String(index),
              label: cohortIdentitiesCompact[index]!,
            }))}
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
            suppressWinnerClaims={decisionSummary.claimSuppressed}
            suppressionReason={decisionSummary.claimSuppressionReason ?? undefined}
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
          const showPrimaryClaims = !decisionSummary.claimSuppressed;
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
                        ? formatPowerScore(r.powerScore).valueText
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
                    <dd class="font-mono text-[var(--bb-data-fg-primary)]">
                      {formatDurationSeconds(r.totalDurationS).valueText}
                    </dd>
                  </div>
                )}
                {showPrimaryClaims && speedup !== null && (
                  <div class="flex justify-between">
                    <dt class="text-[var(--bb-data-fg-muted)]">{vsLabel}</dt>
                    <dd class="font-mono">{formatSpeedup(speedup).valueText}</dd>
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
        suppressionReason={decisionSummary.claimSuppressionReason}
      />
      <ComparabilityReceipt results={results} />
    </div>
  );
}

function CompareGuardrailSummary({
  warningCount,
  warningLabels,
  claimSuppressed,
  suppressionReason,
}: {
  warningCount: number;
  warningLabels: string[];
  claimSuppressed: boolean;
  suppressionReason: string | null;
}) {
  const warningText = warningCount > 0 ? formatWarningClassSummary(warningCount, warningLabels) : null;
  function focusWarningTarget(event: JSX.TargetedMouseEvent<HTMLAnchorElement>) {
    const target =
      document.getElementById(COMPARABILITY_WARNING_TARGET_ID) ?? document.getElementById(COMPARABILITY_RECEIPT_ID);
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView?.({ block: "start" });
    target.focus({ preventScroll: true });
    window.history.replaceState(null, "", `#${target.id}`);
  }
  return (
    <section aria-label="Compare guardrails" class="mb-4 panel-elevated p-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">Comparability guardrails</h2>
          <p class="mt-1 text-sm text-[var(--bb-data-fg-muted)]">
            {claimSuppressed
              ? `Winner claims are suppressed because ${suppressionReason ?? "selected runs are not comparable"}.`
              : "Selected runs share the same benchmark, scale, and phase for winner claims."}
          </p>
          {warningText && (
            <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">
              {warningText}{" "}
              <a href={`#${COMPARABILITY_WARNING_TARGET_ID}`} onClick={focusWarningTarget}>
                Review receipt warnings
              </a>.
            </p>
          )}
        </div>
        {warningCount > 0 ? (
          <a
            href={`#${COMPARABILITY_WARNING_TARGET_ID}`}
            class="no-underline"
            data-testid="compare-warning-link"
            aria-label={`${formatWarningCount(warningCount)}; review comparability receipt warnings`}
            onClick={focusWarningTarget}
          >
            <StatusBadge role="comparison" tone="warning">
              {formatWarningCount(warningCount)}
            </StatusBadge>
          </a>
        ) : (
          <StatusBadge role="comparison" tone={claimSuppressed ? "warning" : "success"}>
            {claimSuppressed ? "Claims suppressed" : "Comparable"}
          </StatusBadge>
        )}
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
  if (new Set(results.map((result) => result.test_type ?? "")).size > 1) {
    reasons.push("phases differ");
  }
  return reasons.length > 0 ? reasons.join(" and ") : null;
}

function CompareBuilder({ pinnedId }: { pinnedId: string | null }) {
  const [candidates, setCandidates] = useState<ResultRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(pinnedId ? [pinnedId] : []),
  );
  const [benchmarkFilter, setBenchmarkFilter] = useState<string>("");
  const [scaleFilter, setScaleFilter] = useState<string>("");
  const [phaseFilter, setPhaseFilter] = useState<string>("");

  useDocumentTitle("Compare · BenchBox Results");

  useEffect(() => {
    let cancelled = false;
    listResults()
      .then((rows) => {
        if (cancelled) return;
        setCandidates(rows);
        // If a run is pinned and filters are still empty, lock the cohort to
        // its benchmark/scale/phase so the candidate list is immediately
        // useful.
        if (pinnedId) {
          const pinned = rows.find((row) => row.result_id === pinnedId);
          if (pinned) {
            setBenchmarkFilter(pinned.benchmark);
            setScaleFilter(String(pinned.scale_factor));
            setPhaseFilter(pinned.test_type ?? "");
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(errMsg(err));
      });
    return () => {
      cancelled = true;
    };
  }, [pinnedId]);

  // First selected run sets the comparable cohort: benchmark + scale + phase
  // must match. This is what `severeCohortMismatchReason` enforces post-hoc;
  // here we enforce it pre-hoc so users can't choose mixed-cohort sets.
  const cohortLock = useMemo(() => {
    if (candidates === null) return null;
    const firstId = Array.from(selectedIds)[0];
    if (!firstId) return null;
    const first = candidates.find((row) => row.result_id === firstId);
    if (!first) return null;
    return {
      benchmark: first.benchmark,
      scale_factor: first.scale_factor,
      test_type: first.test_type ?? "",
    };
  }, [candidates, selectedIds]);

  const cohortSignature = useMemo<CompareCohortSignature | null>(() => {
    if (cohortLock === null) return null;
    return compareCohortSignatureForRow({
      benchmark: cohortLock.benchmark,
      scale_factor: cohortLock.scale_factor,
      test_type: cohortLock.test_type,
    });
  }, [cohortLock]);

  const [compatibleOnly, setCompatibleOnly] = useState(true);

  const benchmarkOptions = useMemo(() => {
    if (candidates === null) return [];
    return Array.from(new Set(candidates.map((row) => row.benchmark))).sort();
  }, [candidates]);
  const scaleOptions = useMemo(() => {
    if (candidates === null) return [];
    const filtered = benchmarkFilter
      ? candidates.filter((row) => row.benchmark === benchmarkFilter)
      : candidates;
    return Array.from(new Set(filtered.map((row) => String(row.scale_factor)))).sort();
  }, [candidates, benchmarkFilter]);
  const phaseOptions = useMemo(() => {
    if (candidates === null) return [];
    const filtered = candidates.filter(
      (row) =>
        (!benchmarkFilter || row.benchmark === benchmarkFilter) &&
        (!scaleFilter || String(row.scale_factor) === scaleFilter),
    );
    return Array.from(new Set(filtered.map((row) => row.test_type ?? ""))).filter(Boolean).sort();
  }, [candidates, benchmarkFilter, scaleFilter]);

  function matchesBuilderFilters(row: ResultRow): boolean {
    if (benchmarkFilter && row.benchmark !== benchmarkFilter) return false;
    if (scaleFilter && String(row.scale_factor) !== scaleFilter) return false;
    if (phaseFilter && (row.test_type ?? "") !== phaseFilter) return false;
    return true;
  }

  const userFilteredRows = useMemo(() => {
    if (candidates === null) return [];
    return candidates.filter(matchesBuilderFilters);
  }, [candidates, benchmarkFilter, scaleFilter, phaseFilter]);

  // Partition by compatibility against the locked cohort. Compatible rows
  // surface above incompatibles so users do not have to scroll past hundreds
  // of disabled rows to find a second compatible candidate (finding #2).
  const partitioned = useMemo(
    () => compareCohortPartition(userFilteredRows, cohortSignature),
    [userFilteredRows, cohortSignature],
  );
  const incompatibleHiddenCount = cohortSignature !== null && compatibleOnly ? partitioned.incompatible.length : 0;
  const selectedRowsForDisplay = useMemo(
    () => candidates?.filter((row) => selectedIds.has(row.result_id)) ?? [],
    [candidates, selectedIds],
  );
  const filteredRows = useMemo(() => {
    const visibleCandidates =
      cohortSignature !== null && compatibleOnly
        ? partitioned.compatible
        : [...partitioned.compatible, ...partitioned.incompatible];
    if (selectedRowsForDisplay.length === 0) return visibleCandidates;
    const selectedResultIds = new Set(selectedRowsForDisplay.map((row) => row.result_id));
    return [...selectedRowsForDisplay, ...visibleCandidates.filter((row) => !selectedResultIds.has(row.result_id))];
  }, [cohortSignature, compatibleOnly, partitioned, selectedRowsForDisplay]);
  const selectableFilteredRows = filteredRows.filter(
    (row) => isCompatible(row) && comparisonExclusionReason(row) === null,
  );
  const zeroSelectable = candidates !== null && filteredRows.length > 0 && selectableFilteredRows.length === 0;
  const zeroSelectableReasons = summarizeCompareExclusionReasons(
    filteredRows.map((row) => comparisonExclusionReason(row) ?? compareCohortLockReason(row, cohortSignature)),
  );

  function isCompatible(row: ResultRow): boolean {
    if (cohortSignature === null) return true;
    return compareCohortMismatches(row, cohortSignature).length === 0;
  }

  function comparisonExclusionReason(row: ResultRow): string | null {
    const reason = row.comparison_exclusion_reason;
    if (typeof reason !== "string" || reason.length === 0) return null;
    return reason;
  }

  function toggleSelection(row: ResultRow) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(row.result_id)) {
        next.delete(row.result_id);
      } else if (next.size < MAX_COMPARE_SELECTIONS && isCompatible(row) && comparisonExclusionReason(row) === null) {
        next.add(row.result_id);
      }
      return next;
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  function clearFilters() {
    setBenchmarkFilter("");
    setScaleFilter("");
    setPhaseFilter("");
  }

  const selectedCount = selectedIds.size;
  const selectedRowsForLaunch = candidates?.filter((row) => selectedIds.has(row.result_id)) ?? [];
  const selectedHasComparisonExclusion = selectedRowsForLaunch.some((row) => comparisonExclusionReason(row) !== null);
  const canLaunch = selectedCount >= 2 && selectedCount <= MAX_COMPARE_SELECTIONS && !selectedHasComparisonExclusion;

  function launch() {
    if (!canLaunch) return;
    toShortIds(Array.from(selectedIds))
      .then((shortIds) => {
        route(buildCompareUrl(shortIds));
      })
      .catch(() => {
        // Fallback: use long ids directly. The existing canonicalize-to-short
        // effect on Compare load will replace them.
        route(buildCompareUrl(Array.from(selectedIds)));
      });
  }

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8" data-testid="compare-builder">
      <Breadcrumb crumbs={[{ label: "Results", href: "/results/" }, { label: "Compare" }]} />

      <section class="mt-6 mb-6 panel-elevated p-5" aria-label="Compare builder intro">
        <p class="text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-subtle)]">Compare</p>
        <h1 class="mt-1 text-2xl font-bold text-[var(--bb-data-fg-primary)]">Pick runs to compare</h1>
        <p class="mt-2 text-sm text-[var(--bb-data-fg-muted)]">
          Select two to four runs from the same benchmark, scale, and phase. The first selection locks the cohort; runs from
          other cohorts will be disabled with a reason. You never need to edit the URL.
        </p>
      </section>

      {loadError && <ErrorMessage title="Could not load candidate runs" message={loadError} />}

      <section class="mb-4 panel p-4" aria-label="Filters">
        <div class="flex flex-wrap gap-3">
          <label class="flex flex-col text-sm">
            <span class="text-xs font-medium text-[var(--bb-data-fg-muted)]">Benchmark</span>
            <select
              class="mt-1 rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm"
              value={benchmarkFilter}
              onChange={(e) => setBenchmarkFilter((e.target as HTMLSelectElement).value)}
            >
              <option value="">Any benchmark</option>
              {benchmarkOptions.map((bm) => (
                <option key={bm} value={bm}>{formatBenchmarkLabel(bm)}</option>
              ))}
            </select>
          </label>
          <label class="flex flex-col text-sm">
            <span class="text-xs font-medium text-[var(--bb-data-fg-muted)]">Scale</span>
            <select
              class="mt-1 rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm"
              value={scaleFilter}
              onChange={(e) => setScaleFilter((e.target as HTMLSelectElement).value)}
            >
              <option value="">Any scale</option>
              {scaleOptions.map((sf) => (
                <option key={sf} value={sf}>SF {sf}</option>
              ))}
            </select>
          </label>
          <label class="flex flex-col text-sm">
            <span class="text-xs font-medium text-[var(--bb-data-fg-muted)]">Phase</span>
            <select
              class="mt-1 rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm"
              value={phaseFilter}
              onChange={(e) => setPhaseFilter((e.target as HTMLSelectElement).value)}
            >
              <option value="">Any phase</option>
              {phaseOptions.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>
          {cohortSignature !== null && (
            <label
              class="flex items-center gap-2 self-end pb-1 text-sm text-[var(--bb-data-fg-muted)]"
              data-testid="compare-builder-compatible-only-label"
            >
              <input
                type="checkbox"
                checked={compatibleOnly}
                onChange={(e) => setCompatibleOnly((e.target as HTMLInputElement).checked)}
                class="h-4 w-4 rounded border-[var(--bb-data-border-strong)]"
                data-testid="compare-builder-compatible-only"
              />
              Compatible only
            </label>
          )}
        </div>
      </section>

      <div class="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm">
        <p class="text-[var(--bb-data-fg-muted)]" data-testid="compare-builder-status">
          {selectedCount === 0
            ? `${formatCandidateCount(filteredRows.length)}. Select at least 2 to launch a comparison.`
            : selectedCount < 2
            ? `1 selected. Select 1 more compatible run to launch.${hiddenIncompatibleSuffix(incompatibleHiddenCount)}`
            : `${formatSelectedCount(selectedCount)}. ${
                cohortLock
                  ? `Cohort: ${humanizeBenchmark(cohortLock.benchmark)} · SF ${cohortLock.scale_factor}${
                      cohortLock.test_type ? ` · ${cohortLock.test_type}` : ""
                    }`
                  : ""
              }`}
        </p>
        <div class="flex gap-2">
          <button
            type="button"
            class="btn btn-secondary"
            onClick={clearSelection}
            disabled={selectedCount === 0}
          >
            Clear selection
          </button>
          <button
            type="button"
            class="btn btn-primary"
            onClick={launch}
            disabled={!canLaunch}
            data-testid="compare-builder-launch"
          >
            Compare {formatCount(selectedCount, "run")}
          </button>
        </div>
      </div>

      {zeroSelectable && (
        <section
          class="mb-4 rounded-lg border border-[var(--bb-tone-warning-border)] bg-[var(--bb-tone-warning-bg)] px-4 py-3 text-sm text-[var(--bb-tone-warning-fg)]"
          data-testid="compare-builder-zero-selectable"
          aria-label="No selectable compare rows"
        >
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 class="font-semibold">No selectable compare rows</h2>
              <p class="mt-1">
                {zeroSelectableReasons.length > 0
                  ? `${zeroSelectableReasons[0]!.count} ${zeroSelectableReasons[0]!.copy.shortText.toLowerCase()} row${
                      zeroSelectableReasons[0]!.count === 1 ? "" : "s"
                    }. ${zeroSelectableReasons[0]!.copy.recoveryHint}`
                  : "The current filters do not expose a comparable run. Clear filters or choose another cohort."}
              </p>
            </div>
            <button type="button" class="btn btn-secondary shrink-0 text-sm" onClick={clearFilters}>
              Clear filters
            </button>
          </div>
        </section>
      )}

      <div class="overflow-x-auto rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
        <table class="min-w-full divide-y divide-[var(--bb-data-border)] text-sm">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              <th scope="col" class="table-th w-12 px-3" aria-label="Select for comparison" />
              <th scope="col" class="table-th text-left">Platform</th>
              <th scope="col" class="table-th text-left">Benchmark</th>
              <th scope="col" class="table-th text-left">Scale</th>
              <th scope="col" class="table-th text-left">Phase</th>
              <th scope="col" class="table-th text-left">Run date</th>
              <th scope="col" class="table-th text-left">Trust</th>
              <th scope="col" class="table-th text-left">Compare state</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)]">
            {candidates === null && (
              <tr>
                <td colSpan={8} class="px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]">
                  Loading candidate runs...
                </td>
              </tr>
            )}
            {candidates !== null && filteredRows.length === 0 && (
              <tr>
                <td colSpan={8} class="px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]">
                  No candidates match the current filters.
                </td>
              </tr>
            )}
            {filteredRows.map((row) => {
              const isSelected = selectedIds.has(row.result_id);
              const compatible = isCompatible(row);
              const comparisonExclusion = comparisonExclusionReason(row);
              const disabledReason = comparisonExclusion !== null
                ? comparisonExclusion
                : !compatible
                ? `Different cohort from selection (${cohortLock?.benchmark}/SF${cohortLock?.scale_factor}${cohortLock?.test_type ? `/${cohortLock.test_type}` : ""})`
                : selectedCount >= MAX_COMPARE_SELECTIONS && !isSelected
                ? `Up to ${MAX_COMPARE_SELECTIONS} runs can be compared`
                : "";
              const isPinned = row.result_id === pinnedId;
              const disabledCopy = describeCompareExclusionReason(disabledReason);
              const reasonId = disabledCopy ? `compare-builder-reason-${row.result_id}` : undefined;
              const selectedOutsideFilters = isSelected && !matchesBuilderFilters(row);
              return (
                <tr
                  key={row.result_id}
                  class={`${isSelected ? "bg-[var(--bb-tone-info-bg)]" : ""} ${
                    !compatible ? "opacity-60" : ""
                  }`}
                  data-testid={`compare-builder-row-${row.result_id}`}
                >
                  <td class="px-3 py-2 align-middle">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      disabled={!isSelected && !!disabledReason}
                      aria-label={compareSelectionLabel({
                        platform: row.platform,
                        benchmark: row.benchmark,
                        scaleFactor: row.scale_factor,
                        phase: row.test_type ?? null,
                        runDate: row.run_date,
                        resultId: row.result_id,
                      })}
                      aria-describedby={reasonId}
                      title={disabledCopy?.detailText ?? (disabledReason || undefined)}
                      onChange={() => toggleSelection(row)}
                      class="h-4 w-4 rounded border-[var(--bb-data-border-strong)]"
                    />
                  </td>
                  <td class="table-td">
                    <div class="font-medium text-[var(--bb-data-fg-primary)]">
                      {row.platform}
                      {isPinned && (
                        <span class="ml-2 text-xs text-[var(--bb-data-fg-subtle)]">(from result detail)</span>
                      )}
                      {selectedOutsideFilters && (
                        <span class="ml-2 text-xs text-[var(--bb-data-fg-subtle)]">(selected outside filters)</span>
                      )}
                    </div>
                    {row.platform_version && (
                      <div class="text-xs text-[var(--bb-data-fg-subtle)]">{row.platform_version}</div>
                    )}
                  </td>
                  <td class="table-td">{humanizeBenchmark(row.benchmark)}</td>
                  <td class="table-td font-mono">SF {row.scale_factor}</td>
                  <td class="table-td">{row.test_type ?? "-"}</td>
                  <td class="table-td">{row.run_date.slice(0, 10)}</td>
                  <td class="table-td"><TrustBadge trustLabel={row.trust_label} compact /></td>
                  <td class="table-td max-w-[16rem]">
                    <CompareReasonStatus
                      id={reasonId}
                      copy={disabledCopy}
                      selected={isSelected}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CompareReasonStatus({
  id,
  copy,
  selected,
}: {
  id?: string;
  copy: CompareExclusionReasonCopy | null;
  selected: boolean;
}) {
  if (copy === null) {
    return (
      <span class="text-xs text-[var(--bb-data-fg-muted)]">
        {selected ? "Selected" : "Selectable"}
      </span>
    );
  }
  return (
    <div id={id} class="text-xs text-[var(--bb-data-fg-muted)]" data-testid="compare-disabled-reason">
      <span class="font-medium text-[var(--bb-tone-warning-fg)]">Disabled reason: {copy.shortText}</span>
      <span class="block">{copy.recoveryHint}</span>
    </div>
  );
}
