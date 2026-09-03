import { useState } from "preact/hooks";
import type { ComponentChildren } from "preact";
import type { DetailResult } from "@/types";
import { humanizeBenchmark, shortHash } from "@/utils";
import { costModelSummary, costScopeSummary, normalizedCostLabel } from "@/lib/costDisplay";
import {
  formatFunding,
  formatTrustLabel,
  formatValidationStatus,
  formatVisibility,
} from "@/lib/displayLabels";
import { StatusBadge } from "@/components/StatusBadge";
import { TuningVerificationBadge } from "@/components/TuningVerificationBadge";
import { formatCpuIdentityProvenance } from "@/lib/hardwareProvenance";

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

/**
 * Row for a full-length identity hash (ADR-1 requested-config / applied-ledger
 * SHA-256). Renders a monospace prefix for readability while the full value
 * stays available in the `title` tooltip, keeping the receipt compact without
 * hiding identity. Missing for legacy bundles that never recorded the hash.
 */
function hashRow(label: string, raw: string | null | undefined): ReceiptRow {
  if (raw === null || raw === undefined || raw === "") return missingRow(label);
  return recordedRow(
    label,
    <code class="font-mono text-xs" title={raw}>
      {shortHash(raw)}
    </code>,
  );
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
  const clientLocalityRow = buildClientLocalityRow(detail);

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
        // ADR-1 bundle-emitted tuning identities, shown as distinct labeled
        // kinds: the canonical requested-config hash and the physical
        // applied-ledger hash. Distinct from the self-derived "Tuning hash"
        // above; null for legacy bundles.
        hashRow("Requested config hash", detail.requested_config_hash),
        hashRow("Applied ledger hash", detail.applied_ledger_hash),
        // ADR-1 tuning verified-state: applied_verified means the applied tuning
        // was corroborated by the post-load introspection receipt; the other
        // states are the honest execution-derived ledger statuses. Missing
        // (behind the disclosure) for legacy bundles predating the ledger.
        // The per-statement applied receipt drills down beneath the badge when
        // the run published one. Its verdicts are rendered verbatim - the
        // explorer never recomputes a verdict or a corroboration decision -
        // and the drill-down is absent entirely when there is no readable
        // receipt, leaving this row exactly as it renders today.
        detail.tuning_validation_status
          ? recordedRow(
              "Tuning verification",
              <>
                <TuningVerificationBadge status={detail.tuning_validation_status} />
                <AppliedReceiptDrilldown raw={detail.applied_receipt} />
              </>,
            )
          : missingRow("Tuning verification"),
      ],
    },
    {
      title: "Environment",
      rows: [
        rowFromString("OS", detail.environment.os),
        rowFromString("Arch", detail.environment.arch),
        rowFromString("CPU family", detail.environment.cpu_family),
        rowFromString("CPU model", detail.environment.cpu_model),
        rowFromString("CPU evidence", detail.environment.cpu_identity_provenance, formatCpuIdentityProvenance),
        rowFromString("CPU count", detail.environment.cpu_count),
        memoryRow(detail.environment.memory_gb),
        rowFromString("Python", detail.environment.python),
        ...(clientLocalityRow ? [clientLocalityRow] : []),
      ],
    },
    {
      title: "Integrity",
      rows: [
        rowFromString("Trust", detail.trust_label, formatTrustLabel),
        // The receipt states funding even when it is "unspecified". The chip
        // stays silent in that case to avoid noise, but a provenance receipt
        // should record that no disclosure was made rather than omit the row.
        rowFromString("Funding", detail.funding, formatFunding),
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
    </section>
  );
}

// ---------------------------------------------------------------------------
// ADR-1 applied-tuning receipt drill-down
//
// `detail.applied_receipt` is the `receipt` sub-object of the run's
// `{stem}.applied.json` companion, carried through the pipeline as an opaque
// JSON string (see explorer_pipeline/transformer.py::_applied_receipt). It is
// parsed here for display only: every verdict shown is the one the platform
// recorded at introspection time. Nothing is recomputed, and no corroboration
// decision is made in the browser.
// ---------------------------------------------------------------------------

interface AppliedReceiptEntry {
  statement?: unknown;
  phase?: unknown;
  verdict?: unknown;
  kind?: unknown;
  table?: unknown;
  expected_columns?: unknown;
  observed_columns?: unknown;
  diff?: unknown;
  reason?: unknown;
  detail?: unknown;
}

interface ParsedAppliedReceipt {
  entries: AppliedReceiptEntry[];
  truncated: boolean;
  originalEntryCount?: number;
}

/**
 * Best-effort parse of the receipt's `entries` list and defensive cap marker.
 *
 * Returns an empty receipt for every degraded shape - absent, empty,
 * unparsable, not an object, or no `entries` array - so the caller renders no
 * drill-down and no error. A published receipt must never be able to break the
 * receipt panel, so this never throws.
 */
function parseAppliedReceipt(raw: string | null | undefined): ParsedAppliedReceipt {
  const empty = { entries: [], truncated: false };
  if (typeof raw !== "string" || raw.trim() === "") return empty;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return empty;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return empty;
  const receipt = parsed as {
    entries?: unknown;
    original_entry_count?: unknown;
    truncated?: unknown;
  };
  if (!Array.isArray(receipt.entries)) return empty;
  return {
    entries: receipt.entries.filter(
      (entry): entry is AppliedReceiptEntry =>
        entry !== null && typeof entry === "object" && !Array.isArray(entry),
    ),
    truncated: receipt.truncated === true,
    originalEntryCount:
      typeof receipt.original_entry_count === "number" ? receipt.original_entry_count : undefined,
  };
}

/**
 * Render a recorded receipt value as text without inventing one. Returns null
 * for anything the receipt did not record, so the field is simply omitted.
 */
function receiptText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value.trim() === "" ? null : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const parts = value.map(receiptText).filter((part): part is string => part !== null);
    return parts.length === 0 ? null : parts.join(", ");
  }
  try {
    return JSON.stringify(value);
  } catch {
    return null;
  }
}

function AppliedReceiptDrilldown({ raw }: { raw?: string | null }) {
  const { entries, truncated, originalEntryCount } = parseAppliedReceipt(raw);
  if (entries.length === 0 && !truncated) return null;
  const entryCount =
    truncated && originalEntryCount !== undefined
      ? `${entries.length} of ${originalEntryCount}; truncated`
      : truncated
        ? `${entries.length}; truncated`
        : String(entries.length);

  return (
    <details class="mt-2" data-testid="applied-receipt-drilldown">
      <summary class="cursor-pointer select-none text-xs text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)]">
        Receipt entries ({entryCount})
      </summary>
      {truncated && (
        <p class="mt-2 text-xs text-[var(--bb-tone-warning-fg)]">
          The published receipt exceeded the defensive receipt bound; the list below is incomplete.
        </p>
      )}
      <ul class="mt-2 list-none space-y-2 p-0">
        {entries.map((entry, index) => (
          <li
            // Receipt entries have no stable identity of their own; index is
            // the honest key for a fixed, render-once verbatim list.
            key={index}
            class="border-t border-[var(--bb-data-border)] pt-2"
            data-testid="applied-receipt-entry"
          >
            <AppliedReceiptEntryBody entry={entry} />
          </li>
        ))}
      </ul>
    </details>
  );
}

function AppliedReceiptEntryBody({ entry }: { entry: AppliedReceiptEntry }) {
  const verdict = receiptText(entry.verdict);
  const statement = receiptText(entry.statement);
  const fields: { label: string; value: string }[] = [
    { label: "Kind", value: receiptText(entry.kind) },
    { label: "Phase", value: receiptText(entry.phase) },
    { label: "Table", value: receiptText(entry.table) },
    { label: "Expected columns", value: receiptText(entry.expected_columns) },
    { label: "Observed columns", value: receiptText(entry.observed_columns) },
    { label: "Diff", value: receiptText(entry.diff) },
    { label: "Reason", value: receiptText(entry.reason) },
    { label: "Detail", value: receiptText(entry.detail) },
  ].filter((field): field is { label: string; value: string } => field.value !== null);

  return (
    <>
      {verdict !== null && (
        <p class="text-xs font-semibold text-[var(--bb-data-fg-primary)]">{verdict}</p>
      )}
      {statement !== null && (
        <code class="mt-1 block break-words font-mono text-xs text-[var(--bb-data-fg-muted)]">
          {statement}
        </code>
      )}
      {fields.length > 0 && (
        <dl class="mt-1 grid grid-cols-[minmax(6rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-1">
          {fields.map((field) => (
            <div key={field.label} class="contents">
              <dt class="text-xs text-[var(--bb-data-fg-muted)]">{field.label}</dt>
              <dd class="min-w-0 break-words text-xs text-[var(--bb-data-fg-primary)]">{field.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </>
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

function buildClientLocalityRow(detail: DetailResult): ReceiptRow | null {
  const env = detail.environment ?? {};
  const region = env.client_region ?? detail.client_region;
  const cloud = env.client_cloud ?? detail.client_cloud;
  const minMs = env.statement_overhead_min_ms ?? detail.statement_overhead_min_ms;
  const medMs = env.statement_overhead_median_ms ?? detail.statement_overhead_median_ms;
  const status = env.link_status ?? detail.link_status;

  const localityParts = [region, cloud].filter((p): p is string => Boolean(p && String(p).trim()));
  const overheadParts: string[] = [];
  if (minMs != null && Number.isFinite(Number(minMs))) {
    overheadParts.push(`${Number(minMs).toFixed(2)} ms min`);
  }
  if (medMs != null && Number.isFinite(Number(medMs))) {
    overheadParts.push(`${Number(medMs).toFixed(2)} ms median`);
  }

  if (localityParts.length === 0 && overheadParts.length === 0 && !status) {
    return null;
  }

  const localityStr = localityParts.length > 0 ? localityParts.join(" / ") : "";
  const overheadStr = overheadParts.length > 0 ? `overhead: ${overheadParts.join(", ")}` : "";

  let displayStr = "";
  if (localityStr && overheadStr) {
    displayStr = `${localityStr} (${overheadStr})`;
  } else {
    displayStr = localityStr || overheadStr;
  }

  if (status && String(status).trim()) {
    displayStr += ` [${status}]`;
  }

  return recordedRow("Client locality", displayStr);
}

function rankingEligibilityRow(value: boolean | null | undefined): ReceiptRow {
  if (value === null || value === undefined) return missingRow("Ranking eligibility");
  return recordedRow("Ranking eligibility", value ? "Eligible" : "Not eligible");
}

export function planDownloadUrl(detail: DetailResult) {
  // Gate on the explicit publication signal, not source-side detection.
  // ``has_plans`` reflects "the source bundle had a *.plans.json sidecar",
  // but the explorer pipeline excludes plan sidecars from bundle discovery
  // (_project/scripts/explorer_pipeline/pipeline.py:439), so plan files are
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
