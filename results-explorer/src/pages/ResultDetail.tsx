import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import type { DetailResult, QueryDisplayTiming, QueryTiming, SortState } from "@/types";
import type { ChartContext } from "@/lib/chartRegistry";
import { getDetailResult, getPrimaryMetricForBenchmark } from "@/lib/duckdbQueries";
import { humanizeBenchmark, errMsg, fmtGeomean, fmtScore } from "@/utils";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Breadcrumb } from "@/components/Breadcrumb";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";
import { TuningBadge } from "@/components/TuningBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { MethodologyDisclosure } from "@/components/MethodologyDisclosure";
import { RunReceipt, planDownloadUrl } from "@/components/RunReceipt";
import { ChartPanel } from "@/components/ChartPanel";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

interface ResultDetailProps extends RoutableProps {
  resultId?: string;
}

type MedianSortKey = "query_id" | "display_ms" | "sample_count";
type RawSortKey = "query_id" | "duration_ms" | "status";
type PrimaryMetric = "power_score" | "display_geomean_ms";
interface DetailState {
  detail: DetailResult;
  primaryMetric: PrimaryMetric;
}

export function ResultDetail({ resultId = "" }: ResultDetailProps) {
  const [detailState, setDetailState] = useState<DetailState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState<MedianSortKey>>({
    key: "query_id",
    direction: "asc",
  });
  const [rawSort, setRawSort] = useState<SortState<RawSortKey>>({
    key: "query_id",
    direction: "asc",
  });
  // Tuning sidecar lazy-load state - hooks must precede any early return.
  const [tuningExpanded, setTuningExpanded] = useState(false);
  const [tuningData, setTuningData] = useState<Record<string, unknown> | null>(null);
  const [tuningLoading, setTuningLoading] = useState(false);
  const [tuningError, setTuningError] = useState<string | null>(null);
  const tuningAbortRef = useRef<AbortController | null>(null);
  const detail = detailState?.detail ?? null;
  const primaryMetric = detailState?.primaryMetric ?? "display_geomean_ms";
  const documentTitle = detail
    ? `${humanizeBenchmark(detail.benchmark)} · ${detail.platform} · SF${detail.scale_factor} · BenchBox Results`
    : "Result · BenchBox Results";
  useDocumentTitle(documentTitle);

  useEffect(() => {
    if (!resultId) {
      setError("No result ID provided.");
      return;
    }
    // Clear stale state so a previous error or detail does not flash during navigation.
    setDetailState(null);
    setError(null);
    setTuningExpanded(false);
    setTuningData(null);
    setTuningError(null);
    tuningAbortRef.current?.abort();
    tuningAbortRef.current = null;
    let cancelled = false;
    getDetailResult(resultId)
      .then(async (data) => {
        if (cancelled) return;
        if (data === null) {
          setError(`No result found for "${resultId}".`);
          return;
        }
        const metric = await getPrimaryMetricForBenchmark(data.benchmark);
        if (cancelled) return;
        setDetailState({ detail: data, primaryMetric: metric });
      })
      .catch((err: unknown) => { if (!cancelled) setError(errMsg(err)); });
    return () => {
      cancelled = true;
      tuningAbortRef.current?.abort();
      tuningAbortRef.current = null;
    };
  }, [resultId]);

  // Hooks must run in the same order on every render - compute memos before
  // any conditional return, guarding inside the factory for the null case.
  const chartContext = useMemo<ChartContext | null>(
    () => (detail ? { kind: "detail" as const, detail, primaryMetric } : null),
    [detail, primaryMetric],
  );

  const sortedMedians = useMemo<QueryDisplayTiming[]>(
    () => {
      if (!detail) return [];
      return [...detail.display_timings].sort((a, b) => {
        const dir = sort.direction === "asc" ? 1 : -1;
        if (sort.key === "query_id") return dir * a.query_id.localeCompare(b.query_id);
        if (sort.key === "display_ms") {
          const av = a.display_ms ?? Infinity;
          const bv = b.display_ms ?? Infinity;
          return dir * (av - bv);
        }
        if (sort.key === "sample_count") return dir * (a.sample_count - b.sample_count);
        return 0;
      });
    },
    [detail, sort],
  );

  const sortedRawQueries = useMemo<QueryTiming[]>(
    () => {
      if (!detail) return [];
      return [...detail.queries].sort((a, b) => {
        const dir = rawSort.direction === "asc" ? 1 : -1;
        if (rawSort.key === "query_id") return dir * a.query_id.localeCompare(b.query_id);
        if (rawSort.key === "duration_ms") return dir * (a.duration_ms - b.duration_ms);
        if (rawSort.key === "status") return dir * a.status.localeCompare(b.status);
        return 0;
      });
    },
    [detail, rawSort],
  );

  if (error) return <ErrorMessage message={error} />;
  if (!detail || !chartContext) return <LoadingSpinner message="Loading result..." />;

  const benchmarkLabel = humanizeBenchmark(detail.benchmark);

  function toggleSort(key: MedianSortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" },
    );
  }

  function sortArrow(key: MedianSortKey) {
    if (sort.key !== key) return " ↕";
    return sort.direction === "asc" ? " ↑" : " ↓";
  }

  function toggleRawSort(key: RawSortKey) {
    setRawSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" },
    );
  }

  function rawSortArrow(key: RawSortKey) {
    if (rawSort.key !== key) return " ↕";
    return rawSort.direction === "asc" ? " ↑" : " ↓";
  }

  // Derive tuning sidecar URL from bundle download URL.
  const tuningUrl = detail.has_tuning && detail.bundle_download_url
    ? detail.bundle_download_url.replace(/\.json$/, ".tuning.json")
    : null;

  function handleTuningExpand() {
    const willExpand = !tuningExpanded;
    setTuningExpanded(willExpand);
    if (willExpand && tuningData === null && !tuningLoading && tuningUrl) {
      setTuningLoading(true);
      const controller = new AbortController();
      tuningAbortRef.current = controller;
      fetch(tuningUrl, { signal: controller.signal })
        .then((r) => r.json() as Promise<Record<string, unknown>>)
        .then((data) => {
          if (controller.signal.aborted) return;
          setTuningData(data);
          setTuningLoading(false);
        })
        .catch((err: unknown) => {
          if (err instanceof DOMException && err.name === "AbortError") return;
          setTuningError("Could not load tuning config.");
          setTuningLoading(false);
        });
    }
  }

  const environmentRows = [
    detail.environment.os ? { label: "OS", value: detail.environment.os } : null,
    detail.environment.arch ? { label: "Arch", value: detail.environment.arch } : null,
    detail.environment.cpu_count !== undefined
      ? { label: "CPUs", value: String(detail.environment.cpu_count) }
      : null,
    detail.environment.memory_gb !== undefined
      ? { label: "Memory", value: `${detail.environment.memory_gb} GB` }
      : null,
    detail.environment.python ? { label: "Python", value: detail.environment.python } : null,
  ].filter((row): row is { label: string; value: string } => row !== null);

  const showTuningSection = detail.tuning_mode !== null || detail.has_tuning;
  const plansUrl = planDownloadUrl(detail);
  const primaryMetricDirection = primaryMetric === "power_score" ? "higher is better" : "lower is better";
  const primaryMetricName = primaryMetric === "power_score" ? "Power score" : "Geomean query time";

  return (
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <Breadcrumb
        crumbs={[
          { label: "Results", href: "/results/" },
          { label: benchmarkLabel, href: `/results/${detail.benchmark}/` },
          { label: detail.platform },
        ]}
      />

      <section aria-label="Result summary" class="mt-6 mb-8 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div class="min-w-0">
            <div class="mb-3 flex flex-wrap items-center gap-3">
              <h1 class="text-3xl font-bold text-gray-900">
                {benchmarkLabel} - {detail.platform}
              </h1>
              <TrustBadge trustLabel={detail.trust_label} />
              <ValidationBadge validationStatus={detail.validation_status} showMissing />
              {detail.tuning_mode && <TuningBadge tuningMode={detail.tuning_mode} />}
              {detail.visibility === "public-curated" && <span class="badge badge-green">curated</span>}
            </div>
            <p class="text-sm text-gray-600">
              {benchmarkLabel} · SF {detail.scale_factor} · {detail.test_type ?? "standard"} · run{" "}
              {detail.run_date.slice(0, 10)}
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <a href={`/results/compare?ids=${detail.result_id}`} class="btn btn-primary">
              Compare this result
            </a>
            <a href={detail.bundle_download_url} class="btn btn-secondary" download>
              Download bundle
            </a>
            {detail.has_plans && plansUrl && (
              <a href={plansUrl} class="btn btn-secondary" download>
                Download plans
              </a>
            )}
          </div>
        </div>

        <div class="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <ResultMetricCard
            label={`Primary metric · ${primaryMetricDirection}`}
            value={formatPrimaryMetric(detail, primaryMetric)}
            helper={primaryMetricName}
          />
          <ResultMetricCard
            label="Scale / phase"
            value={`SF ${detail.scale_factor}`}
            helper={detail.test_type ?? "standard"}
          />
          <ResultMetricCard
            label="Trust / validation"
            value={formatDisplayToken(detail.trust_label)}
            helper={formatDisplayToken(detail.validation_status ?? "validation not recorded")}
          />
          <ResultMetricCard
            label="Wall-clock total"
            value={`${detail.total_duration_s.toFixed(2)} s`}
            helper="Run duration"
          />
        </div>
      </section>

      <div class="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div class="space-y-6">
          <section class="card">
            <h2 class="mb-4 text-base font-semibold text-[var(--bb-data-fg-primary)]">Environment</h2>
            {environmentRows.length > 0 ? (
              <dl class="space-y-2 text-sm">
                {environmentRows.map((row) => (
                  <EnvironmentRow key={row.label} label={row.label} value={row.value} />
                ))}
              </dl>
            ) : (
              <p class="text-sm text-[var(--bb-data-fg-muted)]">Environment metadata was not recorded for this run.</p>
            )}
          </section>

          {showTuningSection && (
            <section class="card">
              <h2 class="mb-3 text-base font-semibold text-[var(--bb-data-fg-primary)]">Tuning Config</h2>
              <div class="space-y-2 text-sm">
                {detail.tuning_mode ? (
                  <div class="flex items-center gap-2">
                    <span class="text-[var(--bb-data-fg-muted)]">Mode:</span>
                    <TuningBadge tuningMode={detail.tuning_mode} />
                  </div>
                ) : (
                  <p class="text-[var(--bb-data-fg-muted)]">Tuning mode not recorded.</p>
                )}
                {tuningUrl ? (
                  <div>
                    <button
                      class="mt-1 cursor-pointer border-0 bg-transparent p-0 text-xs text-[var(--bb-accent-hover)] underline hover:text-[var(--bb-accent)]"
                      onClick={handleTuningExpand}
                    >
                      {tuningExpanded ? "Hide config ↑" : "Show config ↓"}
                    </button>
                    {tuningExpanded && (
                      <div class="mt-2">
                        {tuningLoading && <p class="text-xs text-[var(--bb-data-fg-subtle)]">Loading...</p>}
                        {tuningError && <p role="alert" class="text-xs text-[var(--bb-tone-danger-fg)]">{tuningError}</p>}
                        {tuningData && (
                          <pre class="overflow-x-auto rounded panel-muted p-2 text-xs text-[var(--bb-data-fg-primary)]">
                            {JSON.stringify(tuningData, null, 2)}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <p class="text-xs text-[var(--bb-data-fg-subtle)]">No tuning config recorded.</p>
                )}
              </div>
            </section>
          )}

          {detail.has_plans && !plansUrl && (
            <section class="card">
              <h2 class="mb-2 text-base font-semibold text-gray-900">Execution plans</h2>
              <p class="text-sm text-gray-500">Execution plans were recorded but are not published for download.</p>
            </section>
          )}
        </div>

        <div class="lg:col-span-2 space-y-6">
          {(detail.display_timings.length > 0 || detail.queries.length > 0) && (
            <ChartPanel context={chartContext} />
          )}

          <RunReceipt detail={detail} />

          <section class="card">
            <h2 class="mb-4 text-base font-semibold text-[var(--bb-data-fg-primary)]">
              Query Timings ({detail.display_timings.length})
            </h2>
            <div class="overflow-x-auto" data-testid="detail-timings-scroll-container">
              <div class="mb-2 flex justify-end">
                <span class="bb-scroll-affordance" data-testid="detail-timings-scroll-hint">← scroll →</span>
              </div>
              <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)]">
                <thead class="bg-[var(--bb-surface-data-muted)]">
                  <tr>
                    <th class="p-0" scope="col">
                      <button
                        type="button"
                        class="table-th block w-full text-left cursor-pointer select-none bg-transparent border-0"
                        onClick={() => toggleSort("query_id")}
                      >
                        Query{sortArrow("query_id")}
                      </button>
                    </th>
                    <th class="p-0" scope="col">
                      <button
                        type="button"
                        class="table-th block w-full text-left cursor-pointer select-none bg-transparent border-0"
                        onClick={() => toggleSort("display_ms")}
                      >
                        Median (ms){sortArrow("display_ms")}
                      </button>
                    </th>
                    <th class="p-0" scope="col">
                      <button
                        type="button"
                        class="table-th block w-full text-left cursor-pointer select-none bg-transparent border-0"
                        onClick={() => toggleSort("sample_count")}
                      >
                        Samples{sortArrow("sample_count")}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
                  {sortedMedians.map((q) => (
                    <MedianRow key={q.query_id} timing={q} />
                  ))}
                </tbody>
              </table>
            </div>
            {detail.queries.length > 0 && (
              <details class="mt-4">
                <summary class="cursor-pointer select-none text-sm text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)]">
                  Individual samples ({detail.queries.length})
                </summary>
                <div class="mt-3 overflow-x-auto" data-testid="detail-samples-scroll-container">
                  <div class="mb-2 flex justify-end">
                    <span class="bb-scroll-affordance" data-testid="detail-samples-scroll-hint">← scroll →</span>
                  </div>
                  <table class="min-w-full w-max divide-y divide-[var(--bb-data-border)]">
                    <thead class="bg-[var(--bb-surface-data-muted)]">
                      <tr>
                        <th
                          class="table-th cursor-pointer select-none"
                          role="button"
                          tabIndex={0}
                          onClick={() => toggleRawSort("query_id")}
                          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && toggleRawSort("query_id")}
                        >
                          Query{rawSortArrow("query_id")}
                        </th>
                        <th
                          class="table-th cursor-pointer select-none"
                          role="button"
                          tabIndex={0}
                          onClick={() => toggleRawSort("duration_ms")}
                          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && toggleRawSort("duration_ms")}
                        >
                          Duration (ms){rawSortArrow("duration_ms")}
                        </th>
                        <th
                          class="table-th cursor-pointer select-none"
                          role="button"
                          tabIndex={0}
                          onClick={() => toggleRawSort("status")}
                          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && toggleRawSort("status")}
                        >
                          Status{rawSortArrow("status")}
                        </th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-[var(--bb-data-border)] bg-[var(--bb-surface-data)]">
                      {sortedRawQueries.map((q, i) => (
                        <QueryRow key={`${q.query_id}-${i}`} query={q} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </section>

          <MethodologyDisclosure detail={detail} />
        </div>
      </div>
    </div>
  );
}

function ResultMetricCard({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div class="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
      <div class="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div>
      <div class="mt-1 font-mono text-lg font-semibold text-gray-900">{value}</div>
      <div class="mt-1 text-xs text-gray-500">{helper}</div>
    </div>
  );
}

function formatPrimaryMetric(detail: DetailResult, primaryMetric: PrimaryMetric) {
  if (primaryMetric === "power_score") return fmtScore(detail.power_score);
  return fmtGeomean(detail.display_geomean_ms);
}

function formatDisplayToken(value: string) {
  return value.replace(/[_-]+/g, " ");
}

function EnvironmentRow({ label, value }: { label: string; value: string }) {
  return (
    <div class="flex justify-between gap-2">
      <dt class="text-[var(--bb-data-fg-muted)]">{label}</dt>
      <dd class="text-right font-medium text-[var(--bb-data-fg-primary)]">{value}</dd>
    </div>
  );
}

function MedianRow({ timing }: { timing: QueryDisplayTiming }) {
  return (
    <tr class="hover:bg-[var(--bb-surface-data-muted)]">
      <td class="table-td font-mono font-medium">{timing.query_id}</td>
      <td class="table-td font-mono">
        {timing.display_ms !== null ? timing.display_ms.toFixed(1) : "-"}
      </td>
      <td class="table-td font-mono">{timing.sample_count}</td>
    </tr>
  );
}

function QueryRow({ query }: { query: QueryTiming }) {
  const tone = query.status === "pass" ? "success" : query.status === "fail" ? "danger" : "neutral";

  return (
    <tr class="hover:bg-[var(--bb-surface-data-muted)]">
      <td class="table-td font-mono font-medium">{query.query_id}</td>
      <td class="table-td font-mono">{query.duration_ms.toFixed(1)}</td>
      <td class="table-td">
        <StatusBadge role="validation" tone={tone}>{query.status}</StatusBadge>
      </td>
    </tr>
  );
}
