import { useState } from "preact/hooks";
import type { ComponentChildren } from "preact";
import type { DetailResult } from "@/types";
import { humanizeBenchmark } from "@/utils";
import { costModelSummary, costScopeSummary, normalizedCostLabel } from "@/lib/costDisplay";
import { formatTrustLabel, formatValidationStatus, formatVisibility } from "@/lib/displayLabels";
import { StatusBadge } from "@/components/StatusBadge";

interface RunReceiptProps {
  detail: DetailResult;
  shortId?: string | null;
  isRankingEligible?: boolean | null;
  reproduceCommand?: string | null;
}

interface ReceiptRow {
  label: string;
  value: ComponentChildren;
  // Marked when the row's value is the "Not recorded" placeholder rather than
  // real data. Missing rows move behind the "Show missing metadata"
  // disclosure so the default view is dense with what is actually known.
  isMissing?: boolean;
}

const MISSING_PLACEHOLDER = "Not recorded";

function recordedRow(label: string, value: ComponentChildren): ReceiptRow {
  return { label, value };
}

function missingRow(label: string): ReceiptRow {
  return { label, value: MISSING_PLACEHOLDER, isMissing: true };
}

function rowFromString(
  label: string,
  raw: string | number | null | undefined,
  format: (raw: string) => string = (s) => s,
): ReceiptRow {
  if (raw === null || raw === undefined || raw === "") return missingRow(label);
  return recordedRow(label, format(String(raw)));
}

function rowFromSummary(label: string, value: string): ReceiptRow {
  if (value === MISSING_PLACEHOLDER) return missingRow(label);
  return recordedRow(label, value);
}

export function RunReceipt({
  detail,
  shortId = null,
  isRankingEligible = null,
  reproduceCommand = buildReproduceCommand(detail),
}: RunReceiptProps) {
  const [showMissing, setShowMissing] = useState(false);
  const queryCount = detail.display_timings.length || new Set(detail.queries.map((query) => query.query_id)).size;
  const sampleCount =
    detail.display_timings.reduce((sum, timing) => sum + timing.sample_count, 0) || detail.queries.length;

  const sections = [
    {
      title: "Workload",
      rows: [
        recordedRow("Benchmark", humanizeBenchmark(detail.benchmark)),
        recordedRow("Scale factor", `SF ${detail.scale_factor}`),
        rowFromString("Phase", detail.test_type),
        recordedRow("Query count", String(queryCount)),
        recordedRow("Measurement samples", String(sampleCount)),
      ],
    },
    {
      title: "Platform",
      rows: [
        recordedRow("Platform", detail.platform),
        rowFromString("Platform version", detail.platform_version),
        rowFromString("Driver version", detail.driver_version),
        rowFromString("Execution mode", detail.execution_mode),
        rowFromString("Tuning mode", detail.tuning_mode),
        rowFromString("Tuning hash", detail.tuning_hash),
      ],
    },
    {
      title: "Environment",
      rows: [
        rowFromString("OS", detail.environment.os),
        rowFromString("Arch", detail.environment.arch),
        rowFromString("CPU count", detail.environment.cpu_count),
        memoryRow(detail.environment.memory_gb),
        rowFromString("Python", detail.environment.python),
      ],
    },
    {
      title: "Integrity",
      rows: [
        rowFromString("Trust", detail.trust_label, formatTrustLabel),
        rowFromString("Visibility", detail.visibility, formatVisibility),
        rowFromString("Validation", detail.validation_status, formatValidationStatus),
        rowFromString("Compliance", detail.compliance_class),
        rankingEligibilityRow(isRankingEligible),
      ],
    },
    {
      title: "Artifacts",
      rows: [
        recordedRow("Result ID", <code class="font-mono text-xs">{detail.result_id}</code>),
        rowFromString("Short ID", shortId),
        bundleLinkRow(detail.bundle_download_url),
        plansRow(detail),
        reproduceRow(reproduceCommand),
      ],
    },
    {
      title: "Cost",
      rows: [
        recordedRow("Normalized cost", normalizedCostLabel(detail)),
        rowFromSummary("Cost model", costModelSummary(detail)),
        rowFromSummary("Cost scope", costScopeSummary(detail)),
      ],
    },
  ];

  // Total missing rows across every section. The disclosure stays out of
  // the DOM entirely when nothing is missing — that lets fully-populated
  // results skip the toggle row and keeps the receipt as compact as it
  // is today.
  const totalMissing = sections.reduce(
    (sum, section) => sum + section.rows.filter((row) => row.isMissing).length,
    0,
  );

  return (
    <section id="run-receipt" aria-label="Run receipt" class="panel-elevated p-4">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">Run Receipt</h2>
          <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">Reproducibility, platform, and integrity metadata for this result.</p>
        </div>
        <StatusBadge role="generic" tone="neutral">{detail.result_id.slice(0, 8)}</StatusBadge>
      </div>
      {totalMissing > 0 && (
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--bb-data-fg-muted)]">
          <p>{totalMissing} field{totalMissing === 1 ? "" : "s"} not recorded for this run.</p>
          <button
            type="button"
            class="cursor-pointer border-0 bg-transparent p-0 text-xs text-[var(--bb-accent-hover)] underline hover:text-[var(--bb-accent)]"
            onClick={() => setShowMissing((value) => !value)}
            aria-expanded={showMissing}
            aria-controls="run-receipt-missing-fields-region"
          >
            {showMissing ? "Hide missing metadata" : "Show missing metadata"}
          </button>
        </div>
      )}
      <div
        id="run-receipt-missing-fields-region"
        class="grid gap-4 lg:grid-cols-2"
      >
        {sections.map((section) => (
          <ReceiptSection
            key={section.title}
            title={section.title}
            rows={section.rows}
            showMissing={showMissing}
          />
        ))}
      </div>
    </section>
  );
}

function ReceiptSection({
  title,
  rows,
  showMissing,
}: {
  title: string;
  rows: ReceiptRow[];
  showMissing: boolean;
}) {
  const recordedRows = rows.filter((row) => !row.isMissing);
  const missingRows = rows.filter((row) => row.isMissing);
  const visibleRows = showMissing ? rows : recordedRows;

  return (
    <section aria-labelledby={`run-receipt-${slug(title)}`} class="border-t border-[var(--bb-data-border)] pt-3">
      <h3 id={`run-receipt-${slug(title)}`} class="mb-2 text-xs font-semibold uppercase text-[var(--bb-data-fg-subtle)]">
        {title}
      </h3>
      {recordedRows.length === 0 && !showMissing ? (
        <p class="text-xs text-[var(--bb-data-fg-subtle)]">No {title.toLowerCase()} metadata recorded.</p>
      ) : (
        <dl class="grid grid-cols-[minmax(7rem,0.8fr)_minmax(0,1.2fr)] gap-x-3 gap-y-2 text-sm">
          {visibleRows.map((row) => (
            <div key={row.label} class="contents" data-missing={row.isMissing ? "true" : undefined}>
              <dt class="text-xs text-[var(--bb-data-fg-muted)]">{row.label}</dt>
              <dd
                class={`min-w-0 break-words text-xs font-medium ${
                  row.isMissing
                    ? "text-[var(--bb-data-fg-subtle)] italic"
                    : "text-[var(--bb-data-fg-primary)]"
                }`}
              >
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {!showMissing && recordedRows.length > 0 && missingRows.length > 0 && (
        <p class="mt-2 text-xs text-[var(--bb-data-fg-subtle)]">
          {missingRows.length} field{missingRows.length === 1 ? "" : "s"} not recorded
        </p>
      )}
    </section>
  );
}

function bundleLinkRow(url: string): ReceiptRow {
  if (!url) return missingRow("Bundle");
  return recordedRow(
    "Bundle",
    <a href={url} class="text-xs font-medium no-underline">
      Download bundle
    </a>,
  );
}

function plansRow(detail: DetailResult): ReceiptRow {
  // The Plans row is always present at default — it carries semantic
  // status ("Plans not published" / "Plans available" / a download link)
  // that audit users care about even when no file is reachable.
  if (!detail.has_plans) return recordedRow("Plans", "Plans not published");
  const plansUrl = planDownloadUrl(detail);
  if (plansUrl === null) return recordedRow("Plans", "Plans available");
  return recordedRow(
    "Plans",
    <a href={plansUrl} class="text-xs font-medium no-underline" download>
      Download plans
    </a>,
  );
}

function reproduceRow(reproduceCommand: string | null): ReceiptRow {
  if (!reproduceCommand) return missingRow("Reproduce");
  return recordedRow("Reproduce", <code class="font-mono text-xs">{reproduceCommand}</code>);
}

function memoryRow(value: number | null | undefined): ReceiptRow {
  if (value === null || value === undefined) return missingRow("Memory");
  return recordedRow("Memory", `${value} GB`);
}

function rankingEligibilityRow(value: boolean | null | undefined): ReceiptRow {
  if (value === null || value === undefined) return missingRow("Ranking eligibility");
  return recordedRow("Ranking eligibility", value ? "Eligible" : "Not eligible");
}

export function planDownloadUrl(detail: DetailResult) {
  // Gate on the explicit publication signal, not source-side detection.
  // ``has_plans`` reflects "the source bundle had a *.plans.json sidecar",
  // but the explorer pipeline excludes plan sidecars from bundle discovery
  // (benchbox/core/explorer_pipeline/pipeline.py:439), so plan files are
  // never copied to the published bundles directory and this URL would 404.
  // Only render a link when the pipeline has actually published the file.
  if (!detail.plans_published) return null;
  if (!detail.has_plans || !detail.bundle_download_url) return null;
  if (!detail.bundle_download_url.endsWith(".json")) return null;
  return detail.bundle_download_url.replace(/\.json$/, ".plans.json");
}

function buildReproduceCommand(detail: DetailResult) {
  const parts = [
    "benchbox run",
    `--platform ${detail.platform_id}`,
    `--benchmark ${detail.benchmark}`,
    `--scale ${detail.scale_factor}`,
  ];
  if (detail.test_type) parts.push(`--phases ${detail.test_type}`);
  return parts.join(" ");
}

function slug(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
