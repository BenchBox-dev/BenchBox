import type { ComponentChildren } from "preact";
import type { CompareDecisionSummary } from "@/lib/compareSummary";
import { formatRatio } from "@/lib/compareSummary";
import { fmtGeomean, fmtMs, fmtScore } from "@/utils";

interface CompareSummaryProps {
  summary: CompareDecisionSummary;
}

export function CompareSummary({ summary }: CompareSummaryProps) {
  const winnerPercentiles =
    summary.winner !== null
      ? summary.percentiles.find((entry) => entry.resultId === summary.winner?.resultId)
      : undefined;

  return (
    <section aria-labelledby="compare-decision-summary-title" class="card mb-8">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="compare-decision-summary-title" class="text-base font-semibold text-gray-900">
            Decision Summary
          </h2>
          <p class="mt-1 text-sm font-medium text-gray-800">{summary.headline}</p>
        </div>
        <span class={`badge ${summary.claimSuppressed ? "badge-yellow" : "badge-green"}`}>
          {summary.claimSuppressed ? "Claims suppressed" : "Computed from selected runs"}
        </span>
      </div>

      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Winner">
          {summary.claimSuppressed ? (
            <p class="text-sm text-gray-500">Not claimed</p>
          ) : summary.winner ? (
            <>
              <p class="text-sm font-semibold text-gray-900">{summary.winner.platform}</p>
              <p class="mt-1 font-mono text-xs text-gray-500">
                {formatPrimaryValue(summary.winner.value, summary.primaryMetric)}
              </p>
            </>
          ) : (
            <p class="text-sm text-gray-500">Primary metric unavailable</p>
          )}
        </SummaryCard>

        <SummaryCard label={summary.primaryMetricLabel}>
          {summary.comparisonRatio !== null ? (
            <>
              <p class="font-mono text-sm font-semibold text-gray-900">
                {formatRatio(summary.comparisonRatio)}
              </p>
              <p class="mt-1 text-xs text-gray-500">{summary.comparisonLabel}</p>
            </>
          ) : (
            <p class="text-sm text-gray-500">No comparable primary values</p>
          )}
        </SummaryCard>

        <SummaryCard label="Query wins">
          {summary.claimSuppressed ? (
            <>
              <p class="text-sm text-gray-500">Winner claim suppressed</p>
              <p class="mt-1 text-xs text-gray-500">Use the query diff table for raw evidence.</p>
            </>
          ) : (
            <>
              <p class="font-mono text-sm font-semibold text-gray-900">
                {summary.queryRecord.wins}/{summary.queryRecord.comparableQueries} fastest
              </p>
              <p class="mt-1 text-xs text-gray-500">
                {summary.queryRecord.losses} slower, {summary.queryRecord.ties} tied,{" "}
                {summary.queryRecord.missing} missing
              </p>
            </>
          )}
        </SummaryCard>

        <SummaryCard label="Tail shape">
          {winnerPercentiles?.p50 !== null &&
          winnerPercentiles?.p50 !== undefined &&
          winnerPercentiles.p90 !== null &&
          winnerPercentiles.p99 !== null ? (
            <p class="font-mono text-xs text-gray-700">
              p50 {fmtMs(winnerPercentiles.p50)} · p90 {fmtMs(winnerPercentiles.p90)} · p99{" "}
              {fmtMs(winnerPercentiles.p99)}
            </p>
          ) : (
            <p class="text-sm text-gray-500">Percentiles unavailable</p>
          )}
        </SummaryCard>
      </div>

      {summary.cost && (
        <div class="mt-3 rounded-md border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-600">
          <span class="font-semibold text-gray-700">Cost/performance:</span>{" "}
          {formatCostSummary(summary.cost)}
        </div>
      )}
    </section>
  );
}

function SummaryCard({
  label,
  children,
}: {
  label: string;
  children: ComponentChildren;
}) {
  return (
    <div class="rounded-md border border-gray-100 bg-gray-50 px-3 py-2">
      <h3 class="mb-1 text-xs font-semibold uppercase text-gray-500">{label}</h3>
      {children}
    </div>
  );
}

function formatPrimaryValue(value: number | null, primaryMetric: CompareDecisionSummary["primaryMetric"]) {
  if (primaryMetric === "power_score") return fmtScore(value);
  return fmtGeomean(value);
}

function formatCostSummary(cost: NonNullable<CompareDecisionSummary["cost"]>) {
  if (cost.winnerCostUsd === null || cost.winnerCostPerformanceRatioVsWorst === null) {
    return `${cost.normalizedResultCount} selected run(s) have normalized cost; winner cost is unavailable.`;
  }
  const bestText = cost.winnerIsBestCostPerformance ? "best" : "not best";
  return `winner cost $${cost.winnerCostUsd.toFixed(2)}; ${formatRatio(
    cost.winnerCostPerformanceRatioVsWorst,
  )} cost/performance vs worst normalized row (${bestText}).`;
}
