import type { JSX } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { route } from "preact-router";
import type { RoutableProps } from "preact-router";
import type { DetailResult } from "@/types";
import {
  getDetailResult,
  getExistingResultIds,
  getPrimaryMetricForBenchmark,
  // listResults retired: loading unbounded bench.results bypassed (rx-19)
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  listResults,
  resolveShortId,
  toShortIds,
  type ResultRow,
} from "@/lib/duckdbQueries";
import { humanizeBenchmark, errMsg, fmtGeomean } from "@/utils";
import { canonicalBenchmarkSlug, canonicalPhase, formatBenchmarkLabel } from "@/lib/displayLabels";
import { buildCompareUrl, resultDetailHref, visibleResultIdForRow, MAX_COMPARE_SELECTIONS } from "@/lib/resultLinks";
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
import { FundingChip } from "@/components/FundingChip";
import { TuningBadge } from "@/components/TuningBadge";
import {
  COMPARABILITY_RECEIPT_ID,
  COMPARABILITY_WARNING_TARGET_ID,
  ComparabilityReceipt,
  buildComparabilityFields,
  comparabilityWarningFields,
} from "@/components/ComparabilityReceipt";
import { CompareSummary } from "@/components/CompareSummary";
import {
  DEFAULT_QUERY_DIFF_LIMIT,
  QueryDiffTable,
  QUERY_DIFF_LIMITER_LABELS,
  type QueryDiffLimiter,
  selectQueryIdsForLimiter,
} from "@/components/QueryDiffTable";
import { modeLabel, testTypeLabel } from "@/components/MethodologyDisclosure";
import { vsSlowestRatio } from "@/lib/chartMath";
import {
  buildCompareDecisionSummary,
  COMPARE_TIE_THRESHOLD,
  type ComparePrimaryMetric,
} from "@/lib/compareSummary";
import { IdentityDiffStrip } from "@/components/IdentityDiffStrip";
import { MultiRunHeatmap } from "@/components/MultiRunHeatmap";
import { MultiRunStandings } from "@/components/MultiRunStandings";
import { MeasurementBasisBar } from "@/components/MeasurementBasisBar";
import { useUrlState } from "@/lib/useUrlState";
import { getResultBasisAvailability } from "@/lib/duckdbQueries";
import {
  BASIS_URL_KEY,
  DEFAULT_BASIS,
  basisSerde,
  formatBasisLabel,
  resolvedStatisticsCollapsed,
  isDefaultBasis,
  parseAvailablePassSelections,
  passSelectionsEqual,
  resolveResultsForBasis,
  type PassSelection,
} from "@/lib/measurementBasis";
import { formatDurationSeconds, formatPowerScore, formatSpeedup } from "@/lib/metricFormatters";
import { isValidTimingValue, timingValueForQuery } from "@/lib/displayEligibility";
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
import { ProvenanceLegend } from "@/components/ProvenanceLegend";
import { useDocumentTitle } from "@/lib/useDocumentTitle";
import {
  planCompareIds,
  recoverCompareResults,
  shouldPreserveMultiSelectionUrl,
} from "@/lib/compareRecovery";

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

function formatIdList(ids: string[]): string {
  return ids.map((id) => `“${id}”`).join(", ");
}

function appendCompareNotice(current: string | null, next: string): string {
  return current ? `${current} ${next}` : next;
}

/**
 * Which layout a compare selection renders.
 *
 * Selection COUNT picks the layout, so nobody has to choose a page before
 * choosing runs, and the existing `?ids=` grammar keeps working untouched.
 *
 * Deliberately keyed on DISTINCT runs, not on the raw id list. Two ids that
 * alias to one result are one run and belong on the within-run route, not in a
 * head-to-head that would compare a run against itself.
 */
export type CompareLayout =
  | { readonly kind: "empty" }
  | { readonly kind: "within_run"; readonly resultId: string }
  | { readonly kind: "head_to_head"; readonly runIds: readonly [string, string] }
  | { readonly kind: "multi_run"; readonly runIds: readonly string[] };

/**
 * Choose the layout for a recovered selection.
 *
 * MUST be called on the RECOVERED set, never on the raw `?ids=` list: recovery
 * resolves aliases, drops duplicates and unavailable ids, and caps the
 * selection at MAX_COMPARE_SELECTIONS. Routing on the raw list would pick a
 * layout from a count the page never actually renders -- a five-id URL would
 * choose multi-run and then render four runs.
 */
/**
 * True when a ratio is close enough to 1.0 that calling it a win would be
 * reading noise as a result.
 *
 * Reuses the decision summary's threshold rather than declaring a second one.
 * Two thresholds would eventually disagree, and a page that headlines a win
 * while its own summary calls the same pair a tie is worse than either
 * behaviour on its own.
 */
export function isWithinTieBand(ratio: number | null): boolean {
  if (ratio === null || !Number.isFinite(ratio)) return false;
  return Math.abs(ratio - 1) < COMPARE_TIE_THRESHOLD;
}

export function shouldShowMultiRunStandings(resultIds: readonly string[], claimSuppressed: boolean): boolean {
  return !claimSuppressed && compareLayoutForSelection(resultIds).kind === "multi_run";
}

export function compareLayoutForSelection(resultIds: readonly string[]): CompareLayout {
  const distinct: string[] = [];
  for (const id of resultIds) {
    if (id && !distinct.includes(id)) distinct.push(id);
  }
  const [first, second] = distinct;
  if (first === undefined) return { kind: "empty" };
  if (second === undefined) return { kind: "within_run", resultId: first };
  if (distinct.length === 2) return { kind: "head_to_head", runIds: [first, second] };
  return { kind: "multi_run", runIds: distinct };
}

export function Compare({ url }: CompareProps) {
  const activeUrl = currentCompareUrl(url);
  const [compareState, setCompareState] = useState<CompareState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [baselineIndex, setBaselineIndex] = useState(0);
  // Through the model's serde, not a hand-rolled parser: the grammar is the
  // model's to define, and a shared link has to reproduce the sender's figures
  // exactly. One `basis` parameter, because a cross-run comparison carries
  // exactly one basis -- the URL grammar mirrors the type grammar.
  const [basis, setBasis] = useUrlState(BASIS_URL_KEY, DEFAULT_BASIS, basisSerde);
  // ONE limiter drives the chart and the table. Two independent controls would
  // let the page show a chart of one subset above a table of another, which
  // reads as a data error rather than as two filters.
  const [queryLimiter, setQueryLimiter] = useState<QueryDiffLimiter>("all");
  // Builder mode: rendered when 0 ids are supplied, or when 1 id is supplied
  // (single-result entry from ResultDetail "Compare this result" button).
  // Was previously an error string ("No result IDs provided. Add ?ids=...")
  // or a silent redirect back to ResultDetail; both forced URL editing or
  // dead-ended the user on the page they came from.
  const [builderPinnedId, setBuilderPinnedId] = useState<string | null>(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const [compareNotice, setCompareNotice] = useState<string | null>(null);
  const [preserveRequestedIds, setPreserveRequestedIds] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const results = compareState?.results ?? EMPTY_RESULTS;
  const [availabilityRows, setAvailabilityRows] = useState<Record<string, string>>({});

  // Read the pipeline's precomputed availability rather than deriving it from
  // raw executions: the read model already holds the answer, and pulling every
  // execution row for a 103-query run to re-derive it would be a large
  // download to reach a value we already have.
  useEffect(() => {
    let cancelled = false;
    const ids = results.map((r) => r.result_id);
    if (ids.length === 0) return;
    void Promise.all(ids.map((id) => getResultBasisAvailability(id).catch(() => null))).then((rows) => {
      if (cancelled) return;
      const next: Record<string, string> = {};
      rows.forEach((row, i) => {
        const id = ids[i];
        if (row && id) next[id] = row.available_bases;
      });
      setAvailabilityRows(next);
    });
    return () => {
      cancelled = true;
    };
  }, [results]);

  /**
   * Pass selections EVERY selected run can serve.
   *
   * Intersected, not unioned. Offering a pass one run cannot answer would put
   * a control on the page that empties half the comparison the moment it is
   * used. A run whose availability is unknown (an older snapshot, or a failed
   * read) does not narrow the set -- value resolution reports unavailability
   * per query, where it can name the reason.
   */
  const availablePasses = useMemo<PassSelection[]>(() => {
    const perRun = results
      .map((r) => availabilityRows[r.result_id])
      .filter((raw): raw is string => typeof raw === "string" && raw.length > 0)
      .map((raw) => parseAvailablePassSelections(raw));
    if (perRun.length === 0) return [DEFAULT_BASIS.passes];
    const [first, ...rest] = perRun;
    return (first ?? []).filter((candidate) =>
      rest.every((other) => other.some((p) => passSelectionsEqual(p, candidate))),
    );
  }, [results, availabilityRows]);
  const primaryMetric = compareState?.primaryMetric ?? "display_geomean_ms";
  const normalizedBaselineIndex = results[baselineIndex] ? baselineIndex : 0;
  const resolvedResults = useMemo(
    () => resolveResultsForBasis(results, basis),
    [results, basis],
  );
  const { queryIds: limitedQueryIds } = useMemo(
    () => selectQueryIdsForLimiter(
      resolvedResults,
      normalizedBaselineIndex,
      queryLimiter,
      DEFAULT_QUERY_DIFF_LIMIT,
    ),
    [resolvedResults, normalizedBaselineIndex, queryLimiter],
  );
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
    setCompareNotice(null);
    setPreserveRequestedIds(false);

    const params = searchParamsFromUrl(activeUrl);
    const idsParam = params.get("ids") ?? "";
    const rawIds = idsParam.split(",");
    // Resolve every requested ID before applying the comparison limit so a
    // short ID and its long-form alias consume one slot, not two.
    const plan = planCompareIds(rawIds, rawIds.length);
    let initialNotice: string | null = null;
    if (plan.duplicates.length > 0) {
      initialNotice = `Ignored duplicate result ID${plan.duplicates.length === 1 ? "" : "s"}: ${formatIdList(plan.duplicates)}.`;
    }
    if (initialNotice) setCompareNotice(initialNotice);
    const ids = plan.retained;

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

    recoverCompareResults(ids, MAX_COMPARE_SELECTIONS, {
      resolveId: resolveShortId,
      findExistingIds: getExistingResultIds,
      loadResult: getDetailResult,
      isCancelled: () => cancelled,
    })
      .then(async (recovery) => {
        if (cancelled || recovery === null) return;

        if (recovery.aliases.length > 0) {
          const aliasNotice = `Ignored duplicate result ID${recovery.aliases.length === 1 ? "" : "s"} after alias resolution: ${formatIdList(recovery.aliases)}.`;
          initialNotice = appendCompareNotice(initialNotice, aliasNotice);
          setCompareNotice(initialNotice);
        }

        if (recovery.overflow.length > 0) {
          const aliasResolutionNote = recovery.aliases.length > 0 ? " after alias resolution" : "";
          initialNotice = appendCompareNotice(
            initialNotice,
            `Ignored ${recovery.overflow.length} additional result ID${recovery.overflow.length === 1 ? "" : "s"}${aliasResolutionNote} (${formatIdList(recovery.overflow)}); comparisons are limited to ${MAX_COMPARE_SELECTIONS} unique results.`,
          );
          setCompareNotice(initialNotice);
        }
        if (recovery.unprocessed.length > 0) {
          initialNotice = appendCompareNotice(
            initialNotice,
            `Did not process ${recovery.unprocessed.length} additional result ID${recovery.unprocessed.length === 1 ? "" : "s"} to keep this page responsive; comparisons are limited to ${MAX_COMPARE_SELECTIONS} unique results.`,
          );
          setCompareNotice(initialNotice);
        }
        const details = recovery.recovered.map((entry) => entry.detail);
        if (recovery.failed.length > 0) setPreserveRequestedIds(true);
        if (details.length === 0) {
          if (recovery.failed.length > 0) {
            setError(errMsg(recovery.failed[0]!.error));
          } else {
            const missingIds = recovery.missing.map((entry) => entry.requestedId);
            setError(
              `No result found for: ${missingIds.join(", ")}. ` +
                "These results may have been removed from the published dataset.",
            );
          }
          setLoading(false);
          return;
        }
        if (recovery.missing.length > 0 || recovery.failed.length > 0) {
          const unavailable = [
            ...recovery.missing.map((entry) => entry.requestedId),
            ...recovery.failed.map((entry) => entry.requestedId),
          ];
          initialNotice = appendCompareNotice(
            initialNotice,
            `Ignored unavailable result ID${unavailable.length === 1 ? "" : "s"}: ${formatIdList(unavailable)}.`,
          );
          setCompareNotice(initialNotice);
        }

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

  // Canonicalize URL to the retained short IDs once data is loaded. This also
  // removes stale, duplicate, or excess entries so a copied URL reproduces
  // the same visible comparison state after refresh.
  useEffect(() => {
    const ids = results.map((r) => r.result_id);
    if (ids.length === 0 || typeof window === "undefined") return;
    if (preserveRequestedIds) return;
    const currentParams = new URLSearchParams(window.location.search);
    const currentRawIds = currentParams.get("ids") ?? "";
    // A URL that started as a multi-selection must remain a multi-selection
    // after stale-ID recovery. Keeping its explicit membership is the only
    // way for a one-result recovery to reload into the same comparison surface
    // instead of being reinterpreted as the single-result builder entrypoint.
    if (
      shouldPreserveMultiSelectionUrl(
        currentRawIds.split(","),
        ids.length,
        MAX_COMPARE_SELECTIONS,
      )
    ) {
      setCompareNotice((current) =>
        appendCompareNotice(current, "The original comparison URL is kept so refresh preserves this recovery state."),
      );
      return;
    }
    toShortIds(ids)
      .then((shortIds) => {
        if (shortIds.length !== ids.length || new Set(shortIds).size !== ids.length) {
          setCompareNotice((current) =>
            appendCompareNotice(
              current,
              "The comparison URL could not be canonicalized; retained result order is unchanged.",
            ),
          );
          return;
        }
        const params = new URLSearchParams(window.location.search);
        const currentIds = params.get("ids") ?? "";
        const canonicalIds = shortIds.join(",");
        if (currentIds === canonicalIds) return;
        params.set("ids", canonicalIds);
        const search = params.toString();
        history.replaceState(null, "", `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`);
      })
      .catch(() => {
        setCompareNotice((current) =>
          appendCompareNotice(
            current,
            "The comparison URL could not be canonicalized; sharing it will retry when the dataset is available.",
          ),
        );
      });
  }, [preserveRequestedIds, results]);

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
    return <CompareBuilder pinnedId={builderPinnedId} notice={compareNotice} />;
  }

  if (results.length === 0) return null;

  const benchmark = results[0]?.benchmark ?? "";
  const scaleFactor = results[0]?.scale_factor ?? 0;
  const severeMismatchReason = severeCohortMismatchReason(results);
  const comparabilityFields = buildComparabilityFields(results);
  const comparabilityWarnings = comparabilityWarningFields(comparabilityFields);
  const comparabilityWarningCount = comparabilityWarnings.length;
  const comparabilityWarningLabels = comparabilityWarnings.map((field) => field.label);
  // Compare identity is canonicalized at the cohort boundary. Raw slugs such
  // as `star_schema` remain valid in result data and route links, but aliases
  // must not turn one SSB family into a false mixed-benchmark heading.
  const canonicalBenchmark = canonicalBenchmarkSlug(benchmark);
  const mixedBenchmark = new Set(results.map((result) => canonicalBenchmarkSlug(result.benchmark))).size > 1;
  const benchmarkLabel = mixedBenchmark ? "Mixed Benchmark" : formatBenchmarkLabel(canonicalBenchmark);
  const scaleFactorLabel = new Set(results.map((result) => result.scale_factor)).size > 1
    ? "Mixed scale factors"
    : `SF ${scaleFactor}`;
  const rowCount = results.length;

  /**
   * How many queries every selected run can answer, and how many exist at all.
   *
   * Computed, not approximated. An earlier draft of the basis bar passed the
   * RUN count for both numbers, so a two-run comparison announced "over 2 of 2
   * queries" -- a sentence that looks precise and describes nothing. A stated
   * denominator has to be the real one or it is worse than no denominator.
   *
   * Intersection, matching the model's same-query-set rule: a query any run
   * cannot answer leaves every run's geomean, so it is not part of the set the
   * figures are computed over.
   */
  const queryCoverage = useMemo(() => {
    const allQueryIds = new Set<string>();
    for (const result of resolvedResults) {
      for (const timing of result.display_timings) allQueryIds.add(timing.query_id);
    }
    let shared = 0;
    for (const queryId of allQueryIds) {
      if (resolvedResults.every((result) => timingValueForQuery(result, queryId) !== null)) shared += 1;
    }
    return { shared, total: allQueryIds.size };
  }, [resolvedResults]);

  // Primary metric is loaded async from DuckDB in the effect above; default
  // stays `display_geomean_ms` until the query resolves (matches Python's
  // `_DEFAULT_RANKING`).
  // When a non-default basis is selected, power_score is not applicable because
  // published power scores are strictly calibrated over the official measurement
  // phases. Fall back to display_geomean_ms so rankings and summaries reflect
  // the recomputed query timings under the active basis.
  const effectivePrimaryMetric: ComparePrimaryMetric =
    primaryMetric === "power_score" && !isDefaultBasis(basis)
      ? "display_geomean_ms"
      : (primaryMetric as ComparePrimaryMetric);

  const higherIsBetter = effectivePrimaryMetric === "power_score";

  const primaries: (number | null)[] = resolvedResults.map((r) =>
    effectivePrimaryMetric === "power_score" ? r.power_score : r.display_geomean_ms,
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
  const decisionSummary = buildCompareDecisionSummary(resolvedResults, effectivePrimaryMetric, {
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

  const rowData = resolvedResults.map((r, idx) => ({
    resultId: r.result_id,
    publicId: visibleResultIdForRow(r),
    label: cohortIdentities[idx]!,
    trustLabel: r.trust_label,
    funding: r.funding,
    runDate: r.run_date,
    tuningMode: r.tuning_mode,
    executionMode: r.execution_mode,
    testType: r.test_type,
    powerScore: r.power_score,
    displayGeomeanMs: r.display_geomean_ms,
    totalDurationS: r.total_duration_s,
    driverVersion: r.driver_version,
  }));
  const isMultiRun = compareLayoutForSelection(results.map((r) => r.result_id)).kind === "multi_run";

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

      {compareNotice && (
        <div
          class="mt-4 rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]"
          role="status"
          data-testid="compare-url-notice"
        >
          {compareNotice}
        </div>
      )}

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
      <IdentityDiffStrip
        results={results}
        baselineIndex={normalizedBaselineIndex}
        runLabels={cohortIdentitiesCompact}
      />
      {results.length > 1 && (
        <MeasurementBasisBar
          basis={basis}
          onBasisChange={setBasis}
          availablePasses={availablePasses}
          comparableQueryCount={queryCoverage.shared}
          totalQueryCount={queryCoverage.total}
          runCount={results.length}
          statisticCollapsed={resolvedStatisticsCollapsed(resolvedResults)}
        />
      )}
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

      {results.length > 1 && (
        <div class="panel mb-4 flex flex-wrap items-center justify-between gap-3 px-3 py-2 shadow-sm">
          <div>
            <label class="text-sm font-medium text-[var(--bb-data-fg-primary)]" for="query-limiter">
              Queries shown
            </label>
            <p class="text-xs text-[var(--bb-data-fg-muted)]">
              Applies to the chart and the table together.
            </p>
          </div>
          <Select
            id="query-limiter"
            ariaLabel="Queries shown"
            size="sm"
            value={queryLimiter}
            onChange={(value) => setQueryLimiter(value as QueryDiffLimiter)}
            options={(Object.keys(QUERY_DIFF_LIMITER_LABELS) as QueryDiffLimiter[]).map((key) => ({
              value: key,
              label: QUERY_DIFF_LIMITER_LABELS[key],
            }))}
          />
        </div>
      )}

      {rowCount > 0 && (
        <div class="mb-8">
          <ChartPanel
            context={{ kind: "compare", results: resolvedResults, primaryMetric: effectivePrimaryMetric }}
            baselineIndex={normalizedBaselineIndex}
            onBaselineIndexChange={setBaselineIndex}
            suppressWinnerClaims={decisionSummary.claimSuppressed}
            suppressionReason={decisionSummary.claimSuppressionReason ?? undefined}
            queryFilter={queryLimiter === "all" ? undefined : limitedQueryIds}
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
                {isMultiRun ? (
                  <label class="flex items-center gap-1.5 cursor-pointer text-xs font-medium text-[var(--bb-data-fg-primary)]">
                    <input
                      type="radio"
                      name="compare-baseline-radio"
                      checked={i === normalizedBaselineIndex}
                      onChange={() => setBaselineIndex(i)}
                      aria-label={`Set ${r.label} as baseline`}
                      data-testid={`baseline-radio-${r.resultId}`}
                    />
                    <span class="font-semibold">{r.label}</span>
                  </label>
                ) : (
                  <span class="font-semibold text-[var(--bb-data-fg-primary)]">{r.label}</span>
                )}
                <div class="flex flex-wrap gap-1">
                  <TrustBadge trustLabel={r.trustLabel} compact />
                  <FundingChip funding={r.funding} compact />
                  {r.tuningMode && <TuningBadge tuningMode={r.tuningMode} />}
                  {isFastest && <StatusBadge role="ranking" tone="success">fastest</StatusBadge>}
                </div>
              </div>
              <p class="mb-3 text-xs text-[var(--bb-data-fg-muted)]">
                {r.runDate.slice(0, 10)}
                {r.driverVersion && !r.label.includes(`v${r.driverVersion}`) && ` · v${r.driverVersion}`}
              </p>
              <p class="mb-3 font-mono text-xs text-[var(--bb-data-fg-muted)]">Public ID {r.publicId}</p>
              <dl class="space-y-1 text-sm">
                <div class="flex justify-between">
                  <dt class="text-[var(--bb-data-fg-muted)]">
                    {effectivePrimaryMetric === "power_score" ? "Power score" : "Geomean query time"}
                  </dt>
                  <dd class="font-mono font-medium">
                    {effectivePrimaryMetric === "power_score"
                      ? r.powerScore !== null
                        ? formatPowerScore(r.powerScore).valueText
                        : "-"
                      : fmtGeomean(r.displayGeomeanMs)}
                  </dd>
                </div>
                {effectivePrimaryMetric === "power_score" && (
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
                    {/*
                      Inside the tie band a ratio is not a win in EITHER
                      direction. Rendering the number alone would let a 1.002x
                      read as an advantage once it is rounded to "1.00x" and
                      sat under a "vs slowest" label.
                    */}
                    {isWithinTieBand(speedup) ? (
                      <dd class="text-[var(--bb-data-fg-muted)]" data-testid="headline-tie">
                        Tied
                      </dd>
                    ) : (
                      <dd class="font-mono">{formatSpeedup(speedup).valueText}</dd>
                    )}
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
                href={resultDetailHref(r.resultId)}
                class="mt-3 block text-xs no-underline text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-accent-hover)]"
              >
                View detail →
              </a>
            </div>
          );
        })}
      </div>

      <p class="mb-6 text-xs text-[var(--bb-data-fg-subtle)]">
        <strong>Geomean query time</strong> - geometric mean of per-query execution times ({isDefaultBasis(basis) ? "measurement runs only" : `${formatBasisLabel(basis)} only`}). More
        comparable than wall-clock total when query counts differ. Lower is faster.
      </p>

      {shouldShowMultiRunStandings(
        resolvedResults.map((r) => r.result_id),
        decisionSummary.claimSuppressed,
      ) && (
        <MultiRunStandings
          results={resolvedResults}
          baselineIndex={normalizedBaselineIndex}
          runLabels={cohortIdentitiesCompact}
        />
      )}
      {compareLayoutForSelection(resolvedResults.map((r) => r.result_id)).kind === "multi_run" && (
        <MultiRunHeatmap
          results={resolvedResults}
          baselineIndex={normalizedBaselineIndex}
          runLabels={cohortIdentitiesCompact}
          limiter={queryLimiter}
          orderByDisagreement={queryLimiter === "movement"}
          queryFilter={queryLimiter === "all" ? undefined : limitedQueryIds}
        />
      )}

      <QueryDiffTable
        limiter={queryLimiter}
        results={resolvedResults}
        baselineIndex={normalizedBaselineIndex}
        suppressionReason={decisionSummary.claimSuppressionReason}
        queryFilter={queryLimiter === "all" ? undefined : limitedQueryIds}
      />
      <ComparabilityReceipt results={results} />
      <ProvenanceLegend />
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
  if (new Set(results.map((result) => canonicalBenchmarkSlug(result.benchmark))).size > 1) {
    reasons.push("benchmarks differ");
  }
  if (new Set(results.map((result) => result.scale_factor)).size > 1) {
    reasons.push("scale factors differ");
  }
  // Canonicalize exactly as the cohort builder and selection lock do. Comparing
  // raw values would flag `POWER` against `power` as a severe mismatch and
  // suppress winner/ranking claims for results the builder admitted into one
  // canonical cohort.
  if (new Set(results.map((result) => canonicalPhase(result.test_type))).size > 1) {
    reasons.push("phases differ");
  }
  return reasons.length > 0 ? reasons.join(" and ") : null;
}

function CompareBuilder({ pinnedId, notice }: { pinnedId: string | null; notice: string | null }) {
  // candidates retained for parity but not fetched (rx-19); table is hidden
  const [candidates] = useState<ResultRow[] | null>(null);
  const [_loadError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(pinnedId ? [pinnedId] : []),
  );
  const [benchmarkFilter, setBenchmarkFilter] = useState<string>("");
  const [scaleFilter, setScaleFilter] = useState<string>("");
  const [phaseFilter, setPhaseFilter] = useState<string>("");

  useDocumentTitle("Compare · BenchBox Results");

  useEffect(() => {
    void listResults;
    // rx-19: Candidate table retired; picking lives in Query. Do not load unbounded bench.results.
    return;
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
      test_type: canonicalPhase(first.test_type),
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
    return Array.from(new Set(candidates.map((row) => canonicalBenchmarkSlug(row.benchmark)))).sort();
  }, [candidates]);
  const scaleOptions = useMemo(() => {
    if (candidates === null) return [];
    const filtered = benchmarkFilter
      ? candidates.filter((row) => canonicalBenchmarkSlug(row.benchmark) === benchmarkFilter)
      : candidates;
    return Array.from(new Set(filtered.map((row) => String(row.scale_factor)))).sort();
  }, [candidates, benchmarkFilter]);
  const phaseOptions = useMemo(() => {
    if (candidates === null) return [];
    const filtered = candidates.filter(
      (row) =>
        (!benchmarkFilter || canonicalBenchmarkSlug(row.benchmark) === benchmarkFilter) &&
        (!scaleFilter || String(row.scale_factor) === scaleFilter),
    );
    return Array.from(new Set(filtered.map((row) => canonicalPhase(row.test_type)))).sort();
  }, [candidates, benchmarkFilter, scaleFilter]);

  function matchesBuilderFilters(row: ResultRow): boolean {
    if (benchmarkFilter && canonicalBenchmarkSlug(row.benchmark) !== benchmarkFilter) return false;
    if (scaleFilter && String(row.scale_factor) !== scaleFilter) return false;
    if (phaseFilter && canonicalPhase(row.test_type) !== phaseFilter) return false;
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
  const selectedStatus = formatSelectedCount(selectedCount, "result", MAX_COMPARE_SELECTIONS);
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

      {notice && (
        <div
          class="mt-4 rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-4 py-3 text-sm text-[var(--bb-data-fg-muted)]"
          role="status"
          data-testid="compare-url-notice"
        >
          {notice}
        </div>
      )}

      <section class="mt-6 mb-6 panel-elevated p-5" aria-label="Compare builder intro">
        <p class="text-xs font-semibold uppercase tracking-wide text-[var(--bb-data-fg-subtle)]">Compare</p>
        <h1 class="mt-1 text-2xl font-bold text-[var(--bb-data-fg-primary)]">Pick runs to compare</h1>
        <p class="mt-2 text-sm text-[var(--bb-data-fg-muted)]">
          Choose two to four compatible runs. Your first choice sets the benchmark, scale, and phase; unavailable runs explain
          why they cannot be compared.
        </p>
      </section>

      {_loadError && <ErrorMessage title="Could not load candidate runs" message={_loadError} />}

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
            ? `${formatCandidateCount(filteredRows.length)}. ${selectedStatus}. Select at least 2 to launch a comparison.`
            : selectedCount < 2
            ? `${selectedStatus}. Select 1 more compatible run to launch.${hiddenIncompatibleSuffix(incompatibleHiddenCount)}`
            : `${selectedStatus}. ${
                cohortLock
                  ? `Ranking: ${humanizeBenchmark(cohortLock!.benchmark)} · SF ${cohortLock!.scale_factor}${
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
                  : "The current filters do not expose a comparable run. Clear filters or choose another ranking."}
              </p>
            </div>
            <button type="button" class="btn btn-secondary shrink-0 text-sm" onClick={clearFilters}>
              Clear filters
            </button>
          </div>
        </section>
      )}

      <section class="rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] p-4 text-sm" data-testid="compare-builder-query-cta">
        <p class="font-medium text-[var(--bb-data-fg-primary)]">Pick the second run in Query</p>
        <p class="mt-1 text-[var(--bb-data-fg-muted)]">
          Candidate picking now lives in the paged Query Workbench. Use Query to find the second run and return via the generated compare link. The builder below is limited to the pinned result from ResultDetail or the empty state.
        </p>
        <div class="mt-3 flex flex-wrap items-center gap-3">
          <a href="/results/query" class="btn btn-primary" data-testid="compare-builder-query-link">Open Query</a>

        </div>
      </section>
      {false && (
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
                ? `Different ranking from selection (${cohortLock?.benchmark}/SF${cohortLock?.scale_factor}${cohortLock?.test_type ? `/${cohortLock.test_type}` : ""})`
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
                    <div class="font-medium text-[var(--bb-data-fg-primary)]">{row.platform}</div>
                    <div class="mt-1 flex flex-wrap items-center gap-1.5">
                      <span class="font-mono text-xs text-[var(--bb-data-fg-subtle)]">
                        Public ID {visibleResultIdForRow(row)}
                      </span>
                      {isPinned && (
                        <span class="rounded-full bg-[var(--bb-surface-data-muted)] px-1.5 py-0.5 text-xs text-[var(--bb-data-fg-subtle)]">
                          (from result detail)
                        </span>
                      )}
                      {selectedOutsideFilters && (
                        <span class="rounded-full bg-[var(--bb-surface-data-muted)] px-1.5 py-0.5 text-xs text-[var(--bb-data-fg-subtle)]">
                          selected outside filters
                        </span>
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
                  <td class="table-td">
                    <div class="flex flex-wrap gap-1">
                      <TrustBadge trustLabel={row.trust_label} compact />
                      <FundingChip funding={row.funding} compact />
                    </div>
                  </td>
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
      )}
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
