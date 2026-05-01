import type { ComponentChildren } from "preact";
import type { DetailResult } from "@/types";
import { humanizeBenchmark } from "@/utils";

interface RunReceiptProps {
  detail: DetailResult;
  shortId?: string | null;
  isRankingEligible?: boolean | null;
  reproduceCommand?: string | null;
}

interface ReceiptRow {
  label: string;
  value: ComponentChildren;
}

export function RunReceipt({
  detail,
  shortId = null,
  isRankingEligible = null,
  reproduceCommand = buildReproduceCommand(detail),
}: RunReceiptProps) {
  const queryCount = detail.display_timings.length || new Set(detail.queries.map((query) => query.query_id)).size;
  const sampleCount =
    detail.display_timings.reduce((sum, timing) => sum + timing.sample_count, 0) || detail.queries.length;

  const sections = [
    {
      title: "Workload",
      rows: [
        { label: "Benchmark", value: humanizeBenchmark(detail.benchmark) },
        { label: "Scale factor", value: `SF ${detail.scale_factor}` },
        { label: "Phase", value: valueOrMissing(detail.test_type) },
        { label: "Query count", value: String(queryCount) },
        { label: "Measurement samples", value: String(sampleCount) },
      ],
    },
    {
      title: "Platform",
      rows: [
        { label: "Platform", value: detail.platform },
        { label: "Platform version", value: valueOrMissing(detail.platform_version) },
        { label: "Driver version", value: valueOrMissing(detail.driver_version) },
        { label: "Execution mode", value: valueOrMissing(detail.execution_mode) },
        { label: "Tuning mode", value: valueOrMissing(detail.tuning_mode) },
        { label: "Tuning hash", value: valueOrMissing(detail.tuning_hash) },
      ],
    },
    {
      title: "Environment",
      rows: [
        { label: "OS", value: valueOrMissing(detail.environment.os) },
        { label: "Arch", value: valueOrMissing(detail.environment.arch) },
        { label: "CPU count", value: valueOrMissing(detail.environment.cpu_count) },
        { label: "Memory", value: formatMemory(detail.environment.memory_gb) },
        { label: "Python", value: valueOrMissing(detail.environment.python) },
      ],
    },
    {
      title: "Integrity",
      rows: [
        { label: "Trust", value: detail.trust_label },
        { label: "Visibility", value: detail.visibility },
        { label: "Validation", value: valueOrMissing(detail.validation_status) },
        { label: "Compliance", value: valueOrMissing(detail.compliance_class) },
        { label: "Ranking eligibility", value: formatBoolean(isRankingEligible) },
      ],
    },
    {
      title: "Artifacts",
      rows: [
        { label: "Result ID", value: <code class="font-mono text-xs">{detail.result_id}</code> },
        { label: "Short ID", value: valueOrMissing(shortId) },
        { label: "Bundle", value: renderBundleLink(detail.bundle_download_url) },
        { label: "Plans", value: renderPlansStatus(detail) },
        {
          label: "Reproduce",
          value: reproduceCommand ? <code class="font-mono text-xs">{reproduceCommand}</code> : "Not recorded",
        },
      ],
    },
    {
      title: "Cost",
      rows: [
        { label: "Normalized cost", value: "Not available" },
        { label: "Cost model", value: "Not available" },
        { label: "Cost scope", value: "Not available" },
      ],
    },
  ];

  return (
    <section id="run-receipt" aria-label="Run receipt" class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-gray-900">Run Receipt</h2>
          <p class="mt-1 text-xs text-gray-500">Reproducibility, platform, and integrity metadata for this result.</p>
        </div>
        <span class="badge badge-gray">{detail.result_id.slice(0, 8)}</span>
      </div>
      <div class="grid gap-4 lg:grid-cols-2">
        {sections.map((section) => (
          <ReceiptSection key={section.title} title={section.title} rows={section.rows} />
        ))}
      </div>
    </section>
  );
}

function ReceiptSection({ title, rows }: { title: string; rows: ReceiptRow[] }) {
  return (
    <section aria-labelledby={`run-receipt-${slug(title)}`} class="border-t border-gray-100 pt-3">
      <h3 id={`run-receipt-${slug(title)}`} class="mb-2 text-xs font-semibold uppercase text-gray-500">
        {title}
      </h3>
      <dl class="grid grid-cols-[minmax(7rem,0.8fr)_minmax(0,1.2fr)] gap-x-3 gap-y-2 text-sm">
        {rows.map((row) => (
          <div key={row.label} class="contents">
            <dt class="text-xs text-gray-500">{row.label}</dt>
            <dd class="min-w-0 break-words text-xs font-medium text-gray-900">{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function renderBundleLink(url: string) {
  if (!url) return "Not recorded";
  return (
    <a href={url} class="text-xs font-medium no-underline">
      Download bundle
    </a>
  );
}

function renderPlansStatus(detail: DetailResult) {
  if (!detail.has_plans) return "Plans not published";
  const plansUrl = planDownloadUrl(detail);
  if (plansUrl === null) return "Plans available";
  return (
    <a href={plansUrl} class="text-xs font-medium no-underline" download>
      Download plans
    </a>
  );
}

export function planDownloadUrl(detail: DetailResult) {
  if (!detail.has_plans || !detail.bundle_download_url) return null;
  if (!detail.bundle_download_url.endsWith(".json")) return null;
  return detail.bundle_download_url.replace(/\.json$/, ".plans.json");
}

function valueOrMissing(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value);
}

function formatBoolean(value: boolean | null | undefined) {
  if (value === null || value === undefined) return "Not recorded";
  return value ? "Eligible" : "Not eligible";
}

function formatMemory(value: number | null | undefined) {
  if (value === null || value === undefined) return "Not recorded";
  return `${value} GB`;
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
