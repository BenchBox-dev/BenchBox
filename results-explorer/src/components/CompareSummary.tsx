import type { ComponentChildren } from "preact";
import type { CompareDecisionSummary } from "@/lib/compareSummary";
import { formatRatio } from "@/lib/compareSummary";
import { fmtGeomean, fmtMs, fmtScore } from "@/utils";
import { StatusBadge } from "@/components/StatusBadge";

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
          <h2 id="compare-decision-summary-title" class="text-base font-semibold text-[var(--bb-data-fg-primary)]">
            Decision Summary
          </h2>
          <p class="mt-1 text-sm font-medium text-[var(--bb-data-fg-primary)]">{summary.headline}</p>
        </div>
        <StatusBadge role="computed" tone={summary.claimSuppressed ? "warning" : "info"}>
          {summary.claimSuppressed ? "Claims suppressed" : "Computed from selected runs"}
        </StatusBadge>
      </div>

      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Winner">
          {summary.claimSuppressed ? (
            <p class="text-sm text-[var(--bb-data-fg-muted)]">Not claimed</p>
          ) : summary.winner ? (
            <>
              <p class="text-sm font-semibold text-[var(--bb-data-fg-primary)]">{summary.winner.platform}</p>
              <p class="mt-1 font-mono text-xs text-[var(--bb-data-fg-muted)]">
                {formatPrimaryValue(summary.winner.value, summary.primaryMetric)}
              </p>
            </>
          ) : (
            <p class="text-sm text-[var(--bb-data-fg-muted)]">Primary metric unavailable</p>
          )}
        </SummaryCard>

        <SummaryCard label={summary.primaryMetricLabel}>
          {summary.comparisonRatio !== null ? (
            <>
              <p class="font-mono text-sm font-semibold text-[var(--bb-data-fg-primary)]">
                {formatRatio(summary.comparisonRatio)}
              </p>
              <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">{summary.comparisonLabel}</p>
            </>
          ) : (
            <p class="text-sm text-[var(--bb-data-fg-muted)]">No comparable primary values</p>
          )}
        </SummaryCard>

        <SummaryCard label="Query wins">
          {summary.claimSuppressed ? (
            <>
              <p class="text-sm text-[var(--bb-data-fg-muted)]">Winner claim suppressed</p>
              <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">Use the query diff table for raw evidence.</p>
            </>
          ) : (
            <>
              <p class="font-mono text-sm font-semibold text-[var(--bb-data-fg-primary)]">
                {summary.queryRecord.wins}/{summary.queryRecord.comparableQueries} fastest
              </p>
              <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">
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
            <p class="font-mono text-xs text-[var(--bb-data-fg-primary)]">
              p50 {fmtMs(winnerPercentiles.p50)} · p90 {fmtMs(winnerPercentiles.p90)} · p99{" "}
              {fmtMs(winnerPercentiles.p99)}
            </p>
          ) : (
            <p class="text-sm text-[var(--bb-data-fg-muted)]">Percentiles unavailable</p>
          )}
        </SummaryCard>
      </div>

      {summary.cost && (
        <div class="mt-3 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-2 text-xs text-[var(--bb-data-fg-muted)]">
          <span class="font-semibold text-[var(--bb-data-fg-primary)]">Cost/performance:</span>{" "}
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
    <div class="rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-3 py-2">
      <h3 class="mb-1 text-xs font-semibold uppercase text-[var(--bb-data-fg-subtle)]">{label}</h3>
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
