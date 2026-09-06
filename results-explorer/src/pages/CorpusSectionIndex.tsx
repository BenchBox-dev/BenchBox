import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { EmptyState } from "@/components/EmptyState";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { canonicalBenchmarkSlug, formatBenchmarkLabel } from "@/lib/displayLabels";
import { listResults, type ResultRow } from "@/lib/duckdbQueries";
import { formatCount } from "@/lib/copyFormatters";
import { useDocumentTitle } from "@/lib/useDocumentTitle";
import { useUrlState, type UrlSerde } from "@/lib/useUrlState";
import { errMsg } from "@/utils";

type SectionKind = "benchmarks" | "platforms";
type SectionSort = "name" | "results" | "recent";

interface SectionEntry {
  id: string;
  label: string;
  href: string;
  resultCount: number;
  coverageCount: number;
  latestRun: string;
}

const sectionSortSerde: UrlSerde<SectionSort> = {
  encode: (value) => value,
  decode: (raw) => (raw === "name" || raw === "results" || raw === "recent" ? raw : null),
};

export function CorpusSectionIndex({ kind }: { kind: SectionKind }) {
  const isBenchmarks = kind === "benchmarks";
  const title = isBenchmarks ? "Benchmarks" : "Platforms";
  const singular = isBenchmarks ? "benchmark" : "platform";
  const [rows, setRows] = useState<ResultRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const retriedEmpty = useRef(false);
  const [sort, setSort] = useUrlState<SectionSort>("sort", "name", sectionSortSerde);
  useDocumentTitle(`${title} · BenchBox Results`);

  useEffect(() => {
    let cancelled = false;

    async function loadRows() {
      try {
        let loaded = await listResults();
        if (loaded.length === 0 && !retriedEmpty.current) {
          retriedEmpty.current = true;
          loaded = await listResults();
        }
        if (!cancelled) setRows(loaded);
      } catch (cause) {
        if (!cancelled) setError(errMsg(cause));
      }
    }

    void loadRows();
    return () => {
      cancelled = true;
    };
  }, []);

  const entries = useMemo(() => sortEntries(buildEntries(rows ?? [], kind), sort), [kind, rows, sort]);

  return (
    <div class="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      <header class="mb-8 max-w-3xl">
        <p class="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--bb-accent)]">Published results</p>
        <h1 class="text-3xl font-bold text-[var(--bb-data-fg-primary)]">{title}</h1>
        <p class="mt-3 text-[var(--bb-data-fg-muted)]">
          {isBenchmarks
            ? "Choose a benchmark to see its published runs, participating platforms, and rankings."
            : "Choose a platform to see its published runs across benchmarks and scales."}
        </p>
      </header>

      {rows === null && error === null ? (
        <LoadingSpinner message={`Loading ${kind}...`} />
      ) : error !== null ? (
        <ErrorMessage title={`Could not load ${kind}`} message={error} />
      ) : entries.length === 0 ? (
        <EmptyState
          title={`No published ${kind}`}
          description={`There are no published ${kind} to list yet.`}
          action={
            <a href="/results/" class="btn btn-secondary no-underline">
              Back to leaderboards
            </a>
          }
        />
      ) : (
        <>
          <div class="mb-5 flex flex-wrap items-end justify-between gap-4">
            <p class="text-sm text-[var(--bb-data-fg-muted)]">
              {formatCount(entries.length, `published ${singular}`)}
            </p>
            <label class="flex items-center gap-2 text-sm font-medium text-[var(--bb-data-fg-primary)]">
              Sort {kind}
              <select
                value={sort}
                class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-2 text-sm text-[var(--bb-data-fg-primary)]"
                onChange={(event) => setSort(event.currentTarget.value as SectionSort)}
              >
                <option value="name">Name</option>
                <option value="results">Result count</option>
                <option value="recent">Latest result</option>
              </select>
            </label>
          </div>

          <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid={`${kind}-index-list`}>
            {entries.map((entry) => (
              <li key={entry.id}>
                <a
                  href={entry.href}
                  class="group block h-full rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-5 no-underline shadow-sm transition-colors hover:border-[var(--bb-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--bb-focus-ring)]"
                >
                  <h2 class="text-lg font-semibold text-[var(--bb-data-fg-primary)] group-hover:text-[var(--bb-accent)]">
                    {entry.label}
                  </h2>
                  <dl class="mt-4 grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <dt class="text-[var(--bb-data-fg-subtle)]">Runs</dt>
                      <dd class="mt-1 font-medium text-[var(--bb-data-fg-primary)]">
                        {entry.resultCount.toLocaleString()}
                      </dd>
                    </div>
                    <div>
                      <dt class="text-[var(--bb-data-fg-subtle)]">{isBenchmarks ? "Platforms" : "Benchmarks"}</dt>
                      <dd class="mt-1 font-medium text-[var(--bb-data-fg-primary)]">
                        {entry.coverageCount.toLocaleString()}
                      </dd>
                    </div>
                  </dl>
                  <p class="mt-4 text-xs text-[var(--bb-data-fg-muted)]">
                    Latest result {formatRunDate(entry.latestRun)}
                  </p>
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function buildEntries(rows: ResultRow[], kind: SectionKind): SectionEntry[] {
  const grouped = new Map<string, { label: string; rows: ResultRow[] }>();

  for (const row of rows) {
    const id = kind === "benchmarks" ? canonicalBenchmarkSlug(row.benchmark) : row.platform_id;
    const label = kind === "benchmarks" ? formatBenchmarkLabel(id) : row.platform;
    const existing = grouped.get(id);
    if (existing) {
      existing.rows.push(row);
    } else {
      grouped.set(id, { label, rows: [row] });
    }
  }

  return Array.from(grouped, ([id, group]) => ({
    id,
    label: group.label,
    href: kind === "benchmarks" ? `/results/${encodeURIComponent(id)}/` : `/results/p/${encodeURIComponent(id)}/`,
    resultCount: group.rows.length,
    coverageCount:
      kind === "benchmarks"
        ? new Set(group.rows.map((row) => row.platform_id)).size
        : new Set(group.rows.map((row) => canonicalBenchmarkSlug(row.benchmark))).size,
    latestRun: group.rows.reduce((latest, row) => (row.run_date > latest ? row.run_date : latest), ""),
  }));
}

function sortEntries(entries: SectionEntry[], sort: SectionSort): SectionEntry[] {
  return [...entries].sort((left, right) => {
    if (sort === "results" && left.resultCount !== right.resultCount) return right.resultCount - left.resultCount;
    if (sort === "recent" && left.latestRun !== right.latestRun) return right.latestRun.localeCompare(left.latestRun);
    return left.label.localeCompare(right.label);
  });
}

function formatRunDate(raw: string): string {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(raw));
}
