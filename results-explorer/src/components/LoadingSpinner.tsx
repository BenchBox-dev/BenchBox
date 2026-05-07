interface LoadingSpinnerProps {
  message?: string;
}

export function LoadingSpinner({ message = "Loading..." }: LoadingSpinnerProps) {
  return (
    <section
      role="status"
      aria-live="polite"
      aria-busy="true"
      class="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8"
    >
      <p class="mb-4 text-sm font-medium text-[var(--bb-data-fg-muted)]">{message}</p>
      <div class="overflow-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm">
        <div class="grid grid-cols-4 gap-4 border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] p-4">
          <SkeletonBlock className="h-4" />
          <SkeletonBlock className="h-4" />
          <SkeletonBlock className="h-4" />
          <SkeletonBlock className="h-4" />
        </div>
        <div class="divide-y divide-[var(--bb-data-border)]">
          {Array.from({ length: 5 }).map((_, row) => (
            <div key={row} class="grid grid-cols-4 gap-4 p-4 bb-skeleton-row">
              <SkeletonBlock className="h-4" />
              <SkeletonBlock className="h-4" />
              <SkeletonBlock className="h-4" />
              <SkeletonBlock className="h-4" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" class={`bb-skeleton ${className}`} />;
}

export function MetaLeaderboardSkeleton({
  message = "Initializing static DuckDB snapshot...",
}: LoadingSpinnerProps) {
  return (
    <section
      aria-label="Cross-benchmark leaderboard loading"
      aria-busy="true"
      class="mb-12"
    >
      <p role="status" aria-live="polite" class="mb-4 text-sm font-medium text-[var(--bb-data-fg-muted)]">
        {message}
      </p>
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div class="space-y-2">
          <SkeletonBlock className="h-5 w-64" />
          <SkeletonBlock className="h-3 w-80 max-w-full" />
        </div>
        <div class="flex gap-2">
          <SkeletonBlock className="h-8 w-16" />
          <SkeletonBlock className="h-8 w-16" />
          <SkeletonBlock className="h-8 w-20" />
        </div>
      </div>
      <div class="overflow-x-auto rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm">
        <table aria-hidden="true" class="min-w-full text-sm">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              {Array.from({ length: 6 }).map((_, column) => (
                <th key={column} class="px-4 py-3">
                  <SkeletonBlock className="h-3 w-24" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)]">
            {Array.from({ length: 5 }).map((_, row) => (
              <tr key={row} class="bb-skeleton-row">
                {Array.from({ length: 6 }).map((__, column) => (
                  <td key={column} class="px-4 py-3">
                    <SkeletonBlock className={column === 0 ? "h-4 w-28" : "h-4 w-20"} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function BenchmarkMatrixSkeleton({ message = "Loading matrix..." }: LoadingSpinnerProps) {
  return (
    <section role="status" aria-live="polite" aria-busy="true" class="space-y-4">
      <p class="text-sm font-medium text-[var(--bb-data-fg-muted)]">{message}</p>
      <div class="overflow-x-auto rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm">
        <table aria-hidden="true" class="min-w-full text-sm">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              {Array.from({ length: 7 }).map((_, column) => (
                <th key={column} class="px-4 py-3">
                  <SkeletonBlock className={column === 0 ? "h-3 w-32" : "h-3 w-20"} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)]">
            {Array.from({ length: 6 }).map((_, row) => (
              <tr key={row} class="bb-skeleton-row">
                {Array.from({ length: 7 }).map((__, column) => (
                  <td key={column} class="px-4 py-3">
                    <SkeletonBlock className={column === 0 ? "h-4 w-32" : "h-4 w-16"} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function QueryRowsSkeleton({
  message = "Querying results.duckdb...",
  columns = 7,
}: LoadingSpinnerProps & { columns?: number }) {
  const visibleColumns = Math.max(1, columns);
  return (
    <section
      role="status"
      aria-live="polite"
      aria-busy="true"
      class="overflow-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] shadow-sm"
    >
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 py-3">
        <p class="text-sm font-medium text-[var(--bb-data-fg-muted)]">{message}</p>
        <SkeletonBlock className="h-4 w-28" />
      </div>
      <div class="overflow-x-auto">
        <table aria-hidden="true" class="min-w-full divide-y divide-[var(--bb-data-border)]">
          <thead class="bg-[var(--bb-surface-data-muted)]">
            <tr>
              {Array.from({ length: visibleColumns }).map((_, column) => (
                <th key={column} class="px-4 py-3">
                  <SkeletonBlock className="h-3 w-24" />
                </th>
              ))}
              <th class="px-4 py-3">
                <SkeletonBlock className="h-3 w-12" />
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--bb-data-border)]">
            {Array.from({ length: 6 }).map((_, row) => (
              <tr key={row} class="bb-skeleton-row">
                {Array.from({ length: visibleColumns }).map((__, column) => (
                  <td key={column} class="px-4 py-3">
                    <SkeletonBlock className={column === 0 ? "h-4 w-28" : "h-4 w-20"} />
                  </td>
                ))}
                <td class="px-4 py-3">
                  <SkeletonBlock className="ml-auto h-4 w-12" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function CompareSummarySkeleton({
  message = "Loading results for comparison...",
}: LoadingSpinnerProps) {
  return (
    <section
      role="status"
      aria-live="polite"
      aria-busy="true"
      class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"
    >
      <p class="mb-4 text-sm font-medium text-[var(--bb-data-fg-muted)]">{message}</p>
      <SkeletonBlock className="mb-6 h-4 w-48" />
      <div class="mb-8 space-y-2">
        <SkeletonBlock className="h-8 w-80 max-w-full" />
        <SkeletonBlock className="h-4 w-56" />
      </div>
      <div class="mb-4 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-4 shadow-sm">
        <SkeletonBlock className="mb-3 h-4 w-40" />
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <SkeletonBlock key={index} className="h-16" />
          ))}
        </div>
      </div>
      <div class="mb-8 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-4 shadow-sm">
        <SkeletonBlock className="mb-3 h-4 w-36" />
        <SkeletonBlock className="h-20" />
      </div>
      <div class="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} class="card">
            <SkeletonBlock className="mb-3 h-5 w-32" />
            <SkeletonBlock className="mb-4 h-3 w-24" />
            <div class="space-y-2">
              <SkeletonBlock className="h-4" />
              <SkeletonBlock className="h-4" />
              <SkeletonBlock className="h-4 w-3/4" />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
